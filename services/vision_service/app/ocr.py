import logging
import math
import os
import re
from collections import defaultdict
from functools import lru_cache
from typing import Optional, Tuple

import cv2           # type: ignore
import easyocr       # type: ignore
import numpy as np   # type: ignore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Only English letters and numbers are relevant to registration plates.
OCR_ALLOWLIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# Standard Kenyan private plate: K + 2 letters + 3 digits + 1 letter (e.g. KDC003U)
KENYAN_PLATE_PATTERN = re.compile(r"^K[A-Z]{2}[0-9]{3}[A-Z]$")

# Expected character type per position: L = letter, D = digit.
# Position 0 must additionally be the letter K.
PATTERN = "LLLDDDL"

# Characters the OCR commonly confuses, used only where the expected
# character type at that position is known.
TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1",
            "Z": "2", "S": "5", "G": "6", "B": "8"}
TO_LETTER = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}

# Pattern alignment costs. A substituted character (e.g. 0 -> O) or a dropped
# extra character each cost one unit.
SUBSTITUTION_COST = 1.0
SKIP_COST = 1.0

# Candidate score = OCR confidence * COST_DECAY ** alignment cost.
COST_DECAY = 0.80

# Extra distinct reads that agree on the same plate add this fraction of
# their own score to the plate's total.
AGREEMENT_WEIGHT = 0.15

# Tier 1: a candidate that matches the plate format NATIVELY (no corrections,
# exactly 7 characters) with at least this OCR confidence is preferred first.
HIGH_CONFIDENCE = 0.90

# If the runner-up's total is at least this fraction of the winner's total,
# the result is flagged as contested and sent to review.
CONTESTED_RATIO = 0.75

# Reject suspiciously shaped regions before spending time on OCR.
MIN_PLATE_WIDTH = 40
MIN_PLATE_HEIGHT = 12
MIN_ASPECT_RATIO = 1.8
MAX_ASPECT_RATIO = 6.5

# Output size of the plate-face rectification.
FACE_WIDTH = 800
FACE_HEIGHT = 170

# Output height of the character-line rectification (width follows the shape).
CHAR_OUT_HEIGHT = 160

# Character blob filters (relative to the detector's crop).
CHAR_MIN_HEIGHT_RATIO = 0.18
CHAR_MAX_HEIGHT_RATIO = 0.85
CHAR_MAX_WIDTH_RATIO = 0.25
CHAR_HEIGHT_TOLERANCE = 0.30

# Constrained (segmented) reading: letters-only / digits-only allowlists per slot.
LETTER_ALLOWLIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGIT_ALLOWLIST = "0123456789"
SEGMENT_COUNT = len(PATTERN)

# (group name, plate slots, allowlist)
READ_GROUPS = (
    ("letters", (0, 1, 2), LETTER_ALLOWLIST),
    ("digits", (3, 4, 5), DIGIT_ALLOWLIST),
    ("last", (6,), LETTER_ALLOWLIST),
)

# A constrained read matches the format BY CONSTRUCTION, so a format match is
# not evidence by itself. It is scored like a plate that needed one correction
# and can never trigger the tier-1 shortcut.
CONSTRAINED_COST = 1.0

# --- Partial-plate recovery -------------------------------------------------
# A single-row plate box is about 4.5 : 1. A detector box much narrower than
# that may cover only PART of the plate (seen when a plate fills most of the
# frame and the detector splits it into two halves).
PARTIAL_BOX_RATIO = 3.2

# Two detector boxes are merged into one when they overlap vertically by at
# least this fraction of the smaller box, are separated horizontally by no
# more than this fraction of the wider box, and the merged box is not wider
# than MAX_MERGED_RATIO : 1 (so two separate plates are not fused).
MERGE_MIN_VERTICAL_OVERLAP = 0.60
MERGE_MAX_GAP_RATIO = 0.15
MAX_MERGED_RATIO = 6.0

# "Band" source: when nothing valid is read from a box, widen it sideways by
# BAND_SPAN x its own width on each side (and BAND_VERTICAL_MARGIN vertically)
# and read the wider strip, which can recover the missing half of a plate.
BAND_SPAN = 1.0
BAND_VERTICAL_MARGIN = 0.15

# Last resort: if a plate was DETECTED but nothing valid was read from it,
# search the whole frame for plate-shaped text.
SCENE_FALLBACK_ENABLED = True
SCENE_MAX_SIDE = 1600       # longest side used for the full-frame read
SCENE_MAX_COST = 1.0        # max alignment cost accepted from scene text

# Set OCR_DEBUG_DIR to a folder path to save the crop and each rectified
# plate for visual inspection.
DEBUG_DIR = os.getenv("OCR_DEBUG_DIR")


@lru_cache(maxsize=1)
def get_ocr_reader():
    logger.info("Loading EasyOCR English recognition model.")

    return easyocr.Reader(
        ["en"],
        gpu=False,
        verbose=False,
    )


# ---------------------------------------------------------------------------
# Cropping
# ---------------------------------------------------------------------------

def crop_plate_region(image, bounding_box):
    """
    Crop a detected plate with a small margin.

    Coordinates are clamped to the original image boundaries.
    """

    image_height, image_width = image.shape[:2]

    x1 = int(bounding_box["x1"])
    y1 = int(bounding_box["y1"])
    x2 = int(bounding_box["x2"])
    y2 = int(bounding_box["y2"])

    plate_width = x2 - x1
    plate_height = y2 - y1

    if plate_width <= 0 or plate_height <= 0:
        return None

    # Add a small margin so characters near the edges aren't cut off.
    padding_x = max(3, int(plate_width * 0.05))
    padding_y = max(3, int(plate_height * 0.12))

    x1 = max(0, x1 - padding_x)
    y1 = max(0, y1 - padding_y)

    x2 = min(image_width, x2 + padding_x)
    y2 = min(image_height, y2 + padding_y)

    return image[y1:y2, x1:x2]


# ---------------------------------------------------------------------------
# Rectification method 1: plate face (the white rectangle)
# ---------------------------------------------------------------------------

def order_points(points):
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""
    pts = np.array(points, dtype="float32").reshape(4, 2)

    sums = pts.sum(axis=1)
    diffs = np.diff(pts, axis=1).ravel()

    return np.array(
        [
            pts[np.argmin(sums)],    # top-left
            pts[np.argmin(diffs)],   # top-right
            pts[np.argmax(sums)],    # bottom-right
            pts[np.argmax(diffs)],   # bottom-left
        ],
        dtype="float32",
    )


def find_plate_quad(crop):
    """
    Find the four corners of the white plate face inside the detector's crop.

    Returns an ordered (4, 2) float32 array, or None if no plausible plate
    shape is found.
    """

    height, width = crop.shape[:2]

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    _, bright = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )

    contours, _ = cv2.findContours(
        bright,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    best_contour = None
    best_area = 0

    for contour in contours:
        area = cv2.contourArea(contour)

        # The plate face should fill a decent part of the detector's box.
        if area < 0.15 * width * height:
            continue

        x, y, w, h = cv2.boundingRect(contour)

        # A region touching the crop edge is the bumper/background.
        if x <= 2 or y <= 2 or x + w >= width - 2 or y + h >= height - 2:
            continue

        _, (rect_w, rect_h), _ = cv2.minAreaRect(contour)

        if min(rect_w, rect_h) == 0:
            continue

        ratio = max(rect_w, rect_h) / min(rect_w, rect_h)

        if not 2.5 <= ratio <= 7.0:
            continue

        if area > best_area:
            best_contour = contour
            best_area = area

    if best_contour is None:
        return None

    hull = cv2.convexHull(best_contour)
    perimeter = cv2.arcLength(hull, True)
    approx = cv2.approxPolyDP(hull, 0.02 * perimeter, True)

    if len(approx) == 4:
        return order_points(approx)

    # Fall back to the minimum-area rotated rectangle.
    return order_points(cv2.boxPoints(cv2.minAreaRect(hull)))


def rectify_by_face(crop):
    """Warp the plate face into a flat, front-facing rectangle."""

    quad = find_plate_quad(crop)

    if quad is None:
        return None

    destination = np.array(
        [
            [0, 0],
            [FACE_WIDTH - 1, 0],
            [FACE_WIDTH - 1, FACE_HEIGHT - 1],
            [0, FACE_HEIGHT - 1],
        ],
        dtype="float32",
    )

    matrix = cv2.getPerspectiveTransform(quad, destination)

    return cv2.warpPerspective(
        crop,
        matrix,
        (FACE_WIDTH, FACE_HEIGHT),
        borderMode=cv2.BORDER_REPLICATE,
    )


def trim_margins(image, left=0.10, right=0.02, top=0.08, bottom=0.08):
    """Cut the flag area on the left and the frame edges of a rectified face."""

    height, width = image.shape[:2]

    return image[
        int(height * top):int(height * (1 - bottom)),
        int(width * left):int(width * (1 - right)),
    ]


# ---------------------------------------------------------------------------
# Rectification method 2: character lines (works when the face is not found)
# ---------------------------------------------------------------------------

def find_character_boxes(crop):
    """
    Find dark, character-sized blobs inside the plate crop.

    Returns a list of (x, y, w, h) boxes sorted left to right, or None if
    fewer than 4 consistent character-like blobs are found.
    """

    height, width = crop.shape[:2]

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # Characters are dark on a light plate face.
    _, dark = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )

    count, _, stats, _ = cv2.connectedComponentsWithStats(
        dark,
        connectivity=8,
    )

    boxes = []

    for index in range(1, count):
        x, y, w, h, area = (int(value) for value in stats[index])

        if not (
            CHAR_MIN_HEIGHT_RATIO * height <= h
            <= CHAR_MAX_HEIGHT_RATIO * height
        ):
            continue

        if w > CHAR_MAX_WIDTH_RATIO * width or w == 0:
            continue

        if not 0.8 <= h / w <= 7.0:
            continue

        # Blobs touching the crop edge are frame/background, not characters.
        if x <= 1 or y <= 1 or x + w >= width - 1 or y + h >= height - 1:
            continue

        # Characters are reasonably filled; hollow frames are not.
        if area < 0.2 * w * h:
            continue

        boxes.append((x, y, w, h))

    if len(boxes) < 4:
        return None

    median_height = float(np.median([box[3] for box in boxes]))

    boxes = [
        box for box in boxes
        if abs(box[3] - median_height) <= CHAR_HEIGHT_TOLERANCE * median_height
    ]

    if len(boxes) < 4:
        return None

    boxes.sort(key=lambda box: box[0])

    return boxes


def rectify_by_characters(crop):
    """
    Flatten a tilted plate using the lines through the tops and bottoms of
    its characters.

    The two fitted lines define a quadrilateral that is warped into a
    rectangle, which removes both rotation and most of the perspective.
    """

    boxes = find_character_boxes(crop)

    if boxes is None:
        return None

    xs = np.array([box[0] + box[2] / 2 for box in boxes], dtype="float64")
    tops = np.array([box[1] for box in boxes], dtype="float64")
    bottoms = np.array([box[1] + box[3] for box in boxes], dtype="float64")
    heights = np.array([box[3] for box in boxes], dtype="float64")
    lefts = np.array([box[0] for box in boxes], dtype="float64")
    rights = np.array([box[0] + box[2] for box in boxes], dtype="float64")

    median_height = float(np.median(heights))

    keep = np.ones(len(boxes), dtype=bool)

    # Fit the two lines, drop outlier blobs, refit.
    for _ in range(2):
        if keep.sum() < 4:
            return None

        top_fit = np.polyfit(xs[keep], tops[keep], 1)
        bottom_fit = np.polyfit(xs[keep], bottoms[keep], 1)

        top_residual = np.abs(np.polyval(top_fit, xs) - tops)
        bottom_residual = np.abs(np.polyval(bottom_fit, xs) - bottoms)

        keep = (
            (top_residual <= 0.35 * median_height)
            & (bottom_residual <= 0.35 * median_height)
        )

    if keep.sum() < 4:
        return None

    top_fit = np.polyfit(xs[keep], tops[keep], 1)
    bottom_fit = np.polyfit(xs[keep], bottoms[keep], 1)

    # A steep baseline means the blobs are not a line of plate text.
    if abs(math.degrees(math.atan(top_fit[0]))) > 35:
        return None

    median_height = float(np.median(heights[keep]))

    margin = 0.6 * median_height   # space between the characters and plate edge
    padding = 0.25 * median_height  # space above and below the characters

    x_left = float(lefts[keep].min() - margin)
    x_right = float(rights[keep].max() + margin)

    def top_y(x):
        return float(np.polyval(top_fit, x) - padding)

    def bottom_y(x):
        return float(np.polyval(bottom_fit, x) + padding)

    source = np.array(
        [
            [x_left, top_y(x_left)],
            [x_right, top_y(x_right)],
            [x_right, bottom_y(x_right)],
            [x_left, bottom_y(x_left)],
        ],
        dtype="float32",
    )

    width_length = (
        np.linalg.norm(source[1] - source[0])
        + np.linalg.norm(source[2] - source[3])
    ) / 2

    height_length = (
        np.linalg.norm(source[3] - source[0])
        + np.linalg.norm(source[2] - source[1])
    ) / 2

    if height_length <= 0 or width_length <= 0:
        return None

    out_height = CHAR_OUT_HEIGHT
    out_width = int(np.clip(out_height * width_length / height_length, 240, 1400))

    destination = np.array(
        [
            [0, 0],
            [out_width - 1, 0],
            [out_width - 1, out_height - 1],
            [0, out_height - 1],
        ],
        dtype="float32",
    )

    matrix = cv2.getPerspectiveTransform(source, destination)

    return cv2.warpPerspective(
        crop,
        matrix,
        (out_width, out_height),
        borderMode=cv2.BORDER_REPLICATE,
    )


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

def build_variants(image):
    """
    Grayscale variants for OCR.

    No binarization on purpose: hard thresholding breaks character strokes
    on plates with glare or shadow. Recognition models read gray text better.
    """

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(4, 4),
    ).apply(gray)

    return [
        ("gray", gray),
        ("clahe", clahe),
    ]


# ---------------------------------------------------------------------------
# Raw OCR reads
# ---------------------------------------------------------------------------

def clean_text(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def read_whole_line(reader, gray):
    """
    Skip EasyOCR's text detector and recognize the whole image as one line.

    Only meaningful on a rectified plate, where the entire image IS the line.
    """

    height, width = gray.shape[:2]

    results = reader.recognize(
        gray,
        horizontal_list=[[0, width, 0, height]],
        free_list=[],
        allowlist=OCR_ALLOWLIST,
        decoder="beamsearch",
        beamWidth=5,
    )

    if not results:
        return "", 0.0

    text = clean_text("".join(item[1] for item in results))
    confidence = sum(item[2] for item in results) / len(results)

    return text, float(confidence)


def read_fragments(reader, gray):
    """Normal detection + recognition, joining the pieces left to right."""

    results = reader.readtext(
        gray,
        detail=1,
        paragraph=False,
        allowlist=OCR_ALLOWLIST,
        width_ths=1.5,
    )

    if not results:
        return "", 0.0

    # Sort fragments by the x-position of their top-left corner.
    results.sort(key=lambda item: item[0][0][0])

    text = clean_text("".join(item[1] for item in results))
    confidence = sum(item[2] for item in results) / len(results)

    return text, float(confidence)


READERS = {
    "line": read_whole_line,
    "fragments": read_fragments,
}


# ---------------------------------------------------------------------------
# Pattern alignment
# ---------------------------------------------------------------------------

def match_character(char, position):
    """
    Try to place `char` at plate position `position`.

    Returns (fixed_char, cost) or None if it cannot be placed there.
    """

    if position == 0:
        return (char, 0.0) if char == "K" else None

    if PATTERN[position] == "L":
        if char.isalpha():
            return char, 0.0
        if char in TO_LETTER:
            return TO_LETTER[char], SUBSTITUTION_COST
        return None

    if char.isdigit():
        return char, 0.0
    if char in TO_DIGIT:
        return TO_DIGIT[char], SUBSTITUTION_COST
    return None


def align_to_pattern(text):
    """
    Find the cheapest way to turn `text` into a plate of the form K LL DDD L.

    The text may contain extra characters (which are skipped at a cost) and
    confusable characters (which are substituted at a cost). Missing
    characters cannot be invented, so text shorter than 7 returns None.

    Returns a dict with plate, substitutions, skips and cost, or None.
    """

    length = len(text)
    slots = len(PATTERN)

    if length < slots:
        return None

    infinity = float("inf")

    cost = [[infinity] * (slots + 1) for _ in range(length + 1)]
    back: list[list[Optional[Tuple[int, int, str, Optional[str]]]]] = [
        [None] * (slots + 1) for _ in range(length + 1)
    ]

    cost[0][0] = 0.0

    for i in range(length + 1):
        for j in range(slots + 1):
            current = cost[i][j]

            if current == infinity or i == length:
                continue

            # Option 1: skip this text character as an extra.
            if current + SKIP_COST < cost[i + 1][j]:
                cost[i + 1][j] = current + SKIP_COST
                back[i + 1][j] = (i, j, "skip", None)

            # Option 2: place this text character in the next plate slot.
            if j < slots:
                placed = match_character(text[i], j)

                if placed is not None:
                    fixed, extra = placed

                    if current + extra < cost[i + 1][j + 1]:
                        cost[i + 1][j + 1] = current + extra
                        back[i + 1][j + 1] = (i, j, "match", fixed)

    if cost[length][slots] == infinity:
        return None

    plate: list[str] = [""] * slots
    substitutions = 0
    skips = 0

    i, j = length, slots

    while (i, j) != (0, 0):
        step = back[i][j]
        if step is None:
            return None

        previous_i, previous_j, action, fixed = step

        if action == "skip":
            skips += 1
        else:
            assert fixed is not None
            plate[previous_j] = fixed

            if fixed != text[previous_i]:
                substitutions += 1

        i, j = previous_i, previous_j

    return {
        "plate": "".join(plate),
        "substitutions": substitutions,
        "skips": skips,
        "cost": cost[length][slots],
    }


# ---------------------------------------------------------------------------
# Constrained reading of segmented characters
# ---------------------------------------------------------------------------

def find_split_column(dark, box):
    """
    Find the thinnest column near the middle of a blob that is probably two
    touching characters. Returns an x coordinate, or None if there is no
    real valley.
    """

    x, y, w, h = box

    region = dark[y:y + h, x:x + w] > 0
    columns = region.sum(axis=0)

    low = int(w * 0.30)
    high = max(low + 1, int(w * 0.70))

    window = columns[low:high]

    if window.size == 0:
        return None

    offset = int(np.argmin(window))

    if window[offset] > 0.6 * columns.max():
        return None

    return x + low + offset


def segment_characters(gray):
    """
    Split a flat (rectified) plate strip into exactly SEGMENT_COUNT
    character boxes, left to right.

    Returns a list of (x, y, w, h) tuples, or None when the strip cannot be
    segmented reliably. A failed segmentation is harmless: it just means no
    constrained read is produced for that source.
    """

    height, width = gray.shape[:2]

    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    _, dark = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )

    count, _, stats, _ = cv2.connectedComponentsWithStats(
        dark,
        connectivity=8,
    )

    boxes = []

    for index in range(1, count):
        x, y, w, h, area = (int(value) for value in stats[index])

        if not 0.40 * height <= h <= 0.92 * height:
            continue

        if w == 0 or w > 0.35 * width:
            continue

        # Frame edges and background touch the border; characters do not.
        if x <= 1 or y <= 1 or x + w >= width - 1 or y + h >= height - 1:
            continue

        if area < 0.15 * w * h:
            continue

        boxes.append([x, y, w, h])

    if len(boxes) < 5:
        logger.info("Segmentation found only %d candidate blobs.", len(boxes))
        return None

    median_height = float(np.median([box[3] for box in boxes]))

    boxes = [
        box for box in boxes
        if abs(box[3] - median_height) <= 0.25 * median_height
    ]

    if len(boxes) < 5:
        logger.info("Segmentation found only %d consistent blobs.", len(boxes))
        return None

    boxes.sort(key=lambda box: box[0])

    # Two touching characters appear as one wide blob: try to split it.
    splits = 0

    while len(boxes) < SEGMENT_COUNT and splits < 2:
        median_width = float(np.median([box[2] for box in boxes]))

        widest = max(range(len(boxes)), key=lambda k: boxes[k][2])

        if boxes[widest][2] < 1.5 * median_width:
            break

        cut = find_split_column(dark, boxes[widest])

        if cut is None:
            break

        x, y, w, h = boxes[widest]

        boxes[widest:widest + 1] = [
            [x, y, cut - x, h],
            [cut, y, x + w - cut, h],
        ]

        splits += 1

    # Too many blobs: keep the largest ones (noise and stickers are small).
    if len(boxes) > SEGMENT_COUNT:
        boxes = sorted(
            boxes,
            key=lambda box: box[2] * box[3],
            reverse=True,
        )[:SEGMENT_COUNT]

        boxes.sort(key=lambda box: box[0])

    if len(boxes) != SEGMENT_COUNT:
        logger.info("Segmentation produced %d boxes, expected %d.",
                    len(boxes), SEGMENT_COUNT)
        return None

    return [tuple(box) for box in boxes]


def crop_with_context(gray, boxes, single=False):
    """Crop one or more character boxes and add white padding for context."""

    image_height, image_width = gray.shape[:2]

    x1 = min(box[0] for box in boxes)
    x2 = max(box[0] + box[2] for box in boxes)
    y1 = min(box[1] for box in boxes)
    y2 = max(box[1] + box[3] for box in boxes)

    char_height = y2 - y1
    pad = int(0.15 * char_height)

    crop = gray[
        max(0, y1 - pad):min(image_height, y2 + pad),
        max(0, x1 - pad):min(image_width, x2 + pad),
    ]

    # A lone character needs wider padding so it is not stretched.
    side = int((0.6 if single else 0.25) * char_height)
    vertical = int(0.2 * char_height)

    return cv2.copyMakeBorder(
        crop,
        vertical,
        vertical,
        side,
        side,
        cv2.BORDER_CONSTANT,
        value=255,
    )


def read_crop(reader, crop, allowlist):
    """Recognize one crop as a single line using a restricted alphabet."""

    height, width = crop.shape[:2]

    results = reader.recognize(
        crop,
        horizontal_list=[[0, width, 0, height]],
        free_list=[],
        allowlist=allowlist,
        decoder="beamsearch",
        beamWidth=5,
    )

    if not results:
        return "", 0.0

    text = clean_text("".join(item[1] for item in results))
    confidence = sum(item[2] for item in results) / len(results)

    return text, float(confidence)


def read_constrained(reader, gray, boxes):
    """
    Read segmented characters with position-specific alphabets.

    Slots 1-3 and 7 may only be letters, slots 4-6 may only be digits. The
    recognizer therefore cannot answer B where the plate has a 3, or O where
    it has a 0. Each group is read with context first; if the group read has
    the wrong length, every character in it is read on its own.

    Returns {"text", "confidence", "groups"} or None. Confidence is the
    weakest group, because a plate is only as reliable as its worst part.
    """

    texts = []
    confidences = []
    groups = []

    for name, slots, allowlist in READ_GROUPS:
        subset = [boxes[slot] for slot in slots]

        text, confidence = read_crop(
            reader,
            crop_with_context(gray, subset, single=len(slots) == 1),
            allowlist,
        )

        method = "group"

        if len(text) != len(slots):
            characters = []
            character_confidences = []

            for box in subset:
                char_text, char_confidence = read_crop(
                    reader,
                    crop_with_context(gray, [box], single=True),
                    allowlist,
                )

                if len(char_text) != 1:
                    return None

                characters.append(char_text)
                character_confidences.append(char_confidence)

            text = "".join(characters)
            confidence = min(character_confidences)
            method = "per_character"

        texts.append(text)
        confidences.append(confidence)

        groups.append({
            "group": name,
            "text": text,
            "confidence": round(confidence, 4),
            "method": method,
        })

    plate = "".join(texts)

    if not KENYAN_PLATE_PATTERN.fullmatch(plate):
        return None

    return {
        "text": plate,
        "confidence": min(confidences),
        "groups": groups,
    }


# ---------------------------------------------------------------------------
# Candidate collection and selection
# ---------------------------------------------------------------------------

def make_candidate(source, variant, mode, text, confidence):
    """Build a free-read candidate and align it to the plate pattern."""

    aligned = align_to_pattern(text)

    candidate = {
        "source": source,
        "variant": variant,
        "mode": mode,
        "normalized_text": text,
        "ocr_confidence": round(confidence, 4),
        "corrected_text": None,
        "substitutions": None,
        "skips": None,
        "cost": None,
        "native_valid": False,
        "constrained": False,
        "score": 0.0,
    }

    if aligned:
        candidate.update({
            "corrected_text": aligned["plate"],
            "substitutions": aligned["substitutions"],
            "skips": aligned["skips"],
            "cost": aligned["cost"],
            "native_valid": aligned["cost"] == 0,
            "score": round(
                confidence * (COST_DECAY ** aligned["cost"]),
                4,
            ),
        })

    return candidate


def make_constrained_candidate(source, variant, result):
    return {
        "source": source,
        "variant": variant,
        "mode": "constrained",
        "normalized_text": result["text"],
        "ocr_confidence": round(result["confidence"], 4),
        "corrected_text": result["text"],
        "substitutions": 0,
        "skips": 0,
        "cost": CONSTRAINED_COST,
        "native_valid": False,
        "constrained": True,
        "score": round(
            result["confidence"] * (COST_DECAY ** CONSTRAINED_COST),
            4,
        ),
        "groups": result["groups"],
    }


def save_segmentation_debug(name, gray, boxes):
    if not DEBUG_DIR or boxes is None:
        return

    canvas = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    for number, (x, y, w, h) in enumerate(boxes, start=1):
        cv2.rectangle(canvas, (x, y), (x + w, y + h), (0, 0, 255), 2)
        cv2.putText(
            canvas,
            str(number),
            (x, max(12, y - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            1,
        )

    save_debug_image(name, canvas)


def collect_candidates(reader, sources, debug_prefix=None):
    """
    Run every source/variant/mode combination and return DISTINCT reads.

    Reads are deduplicated by (source, variant, kind, text), so the `line`
    and `fragments` modes returning the same text count as one read.

    Each source is (name, image, free read modes, segment?). Sources marked
    for segmentation additionally get constrained per-slot reads.

    Returns (candidates, segmentation) where segmentation maps each segmented
    source name to whether segmentation succeeded.
    """

    distinct = {}
    segmentation = {}

    def add(candidate):
        key = (
            candidate["source"],
            candidate["variant"],
            candidate["constrained"],
            candidate["normalized_text"],
        )

        existing = distinct.get(key)

        if existing and existing["ocr_confidence"] >= candidate["ocr_confidence"]:
            return

        distinct[key] = candidate

    for source_name, source_image, modes, segment in sources:
        variants = build_variants(source_image)

        for variant_name, gray in variants:
            for mode in modes:
                try:
                    text, confidence = READERS[mode](reader, gray)
                except Exception:
                    logger.exception(
                        "OCR read failed (%s/%s/%s).",
                        source_name,
                        variant_name,
                        mode,
                    )
                    continue

                if text:
                    add(make_candidate(
                        source_name,
                        variant_name,
                        mode,
                        text,
                        confidence,
                    ))

        if not segment:
            continue

        # Segment once on the plain grayscale variant, read on every variant.
        boxes = segment_characters(variants[0][1])

        segmentation[source_name] = boxes is not None

        if boxes is None:
            continue

        if debug_prefix:
            save_segmentation_debug(
                f"{debug_prefix}_{source_name}_segments.jpg",
                variants[0][1],
                boxes,
            )

        for variant_name, gray in variants:
            try:
                result = read_constrained(reader, gray, boxes)
            except Exception:
                logger.exception(
                    "Constrained read failed (%s/%s).",
                    source_name,
                    variant_name,
                )
                continue

            if result:
                add(make_constrained_candidate(
                    source_name,
                    variant_name,
                    result,
                ))

    return list(distinct.values()), segmentation


def choose_plate(candidates):
    """
    Pick the most trustworthy plate from all distinct reads.

    Tier 1: a plate with a native, uncorrected read at >= HIGH_CONFIDENCE.
    Tier 2: otherwise, the plate with the highest total score.

    A plate's total score is its best candidate score plus a fraction of the
    scores of other distinct reads that agree with it. Confidence always
    matters; agreement helps but cannot outvote a clearly better read.
    """

    aligned = [c for c in candidates if c["corrected_text"]]

    if not aligned:
        best = max(
            candidates,
            key=lambda item: item["ocr_confidence"],
            default=None,
        )

        return {
            "text": best["normalized_text"] if best else None,
            "confidence": best["ocr_confidence"] if best else 0.0,
            "format_valid": False,
            "reads": 0,
            "native_reads": 0,
            "constrained_reads": 0,
            "corrections": None,
            "tier": None,
            "contested": False,
            "total_score": 0.0,
            "alternatives": [],
        }

    groups = defaultdict(list)

    for candidate in aligned:
        groups[candidate["corrected_text"]].append(candidate)

    summaries = []

    for plate, group in groups.items():
        scores = sorted((c["score"] for c in group), reverse=True)

        total = scores[0] + AGREEMENT_WEIGHT * sum(scores[1:])

        best_candidate = max(group, key=lambda item: item["score"])

        summaries.append({
            "plate": plate,
            "total": round(total, 4),
            "reads": len(group),
            "native_reads": sum(1 for c in group if c["native_valid"]),
            "constrained_reads": sum(
                1 for c in group if c.get("constrained")
            ),
            "best_confidence": best_candidate["ocr_confidence"],
            "best_native_confidence": max(
                (c["ocr_confidence"] for c in group if c["native_valid"]),
                default=0.0,
            ),
            "min_cost": min(c["cost"] for c in group),
        })

    summaries.sort(key=lambda item: item["total"], reverse=True)

    tier_one = [
        s for s in summaries
        if s["best_native_confidence"] >= HIGH_CONFIDENCE
    ]

    if tier_one:
        winner = max(tier_one, key=lambda item: item["total"])
        tier = 1
    else:
        winner = summaries[0]
        tier = 2

    others = [s for s in summaries if s["plate"] != winner["plate"]]

    contested = bool(
        others
        and others[0]["total"] >= CONTESTED_RATIO * winner["total"]
    )

    return {
        "text": winner["plate"],
        "confidence": winner["best_confidence"],
        "format_valid": bool(KENYAN_PLATE_PATTERN.fullmatch(winner["plate"])),
        "reads": winner["reads"],
        "native_reads": winner["native_reads"],
        "constrained_reads": winner["constrained_reads"],
        "corrections": winner["min_cost"],
        "tier": tier,
        "contested": contested,
        "total_score": winner["total"],
        "best_native_confidence": winner["best_native_confidence"],
        "alternatives": [
            {
                "text": s["plate"],
                "score": s["total"],
                "reads": s["reads"],
            }
            for s in summaries[:3]
        ],
    }


# ---------------------------------------------------------------------------
# Optional registry cross-check
# ---------------------------------------------------------------------------

def levenshtein(a, b):
    if a == b:
        return 0

    previous = list(range(len(b) + 1))

    for i, char_a in enumerate(a, start=1):
        current = [i]

        for j, char_b in enumerate(b, start=1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (char_a != char_b),
            ))

        previous = current

    return previous[-1]


def registry_match(text, known_plates):
    """
    Compare a recognized plate with registered plates.

    A near match (one character off) means the read may be wrong OR the
    plate may be a clone, so it must go to a human instead of being allowed
    automatically.
    """

    if not text or not known_plates:
        return None

    known = {clean_text(plate) for plate in known_plates if plate}

    return {
        "exact_match": text in known,
        "near_matches": sorted(
            plate for plate in known
            if plate != text and levenshtein(text, plate) <= 1
        ),
    }


# ---------------------------------------------------------------------------
# Debug helper
# ---------------------------------------------------------------------------

def save_debug_image(name, image):
    if not DEBUG_DIR or image is None:
        return

    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        cv2.imwrite(os.path.join(DEBUG_DIR, name), image)
    except Exception:
        logger.exception("Could not write OCR debug image.")


# ---------------------------------------------------------------------------
# Detection merging, band crops and full-frame fallback
# ---------------------------------------------------------------------------

def _box_tuple(box):
    return (
        float(box["x1"]),
        float(box["y1"]),
        float(box["x2"]),
        float(box["y2"]),
    )


def _boxes_belong_together(a, b):
    """True when two boxes look like two halves of one single-row plate."""

    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    smaller_height = min(ay2 - ay1, by2 - by1)

    if smaller_height <= 0:
        return False

    vertical_overlap = min(ay2, by2) - max(ay1, by1)

    if vertical_overlap / smaller_height < MERGE_MIN_VERTICAL_OVERLAP:
        return False

    gap = max(ax1, bx1) - min(ax2, bx2)    # negative when they overlap
    widest = max(ax2 - ax1, bx2 - bx1)

    if gap > MERGE_MAX_GAP_RATIO * widest:
        return False

    union_width = max(ax2, bx2) - min(ax1, bx1)
    union_height = max(ay2, by2) - min(ay1, by1)

    return union_height > 0 and union_width / union_height <= MAX_MERGED_RATIO


def merge_plate_detections(detections):
    """
    Merge detector boxes that are fragments of the same plate.

    Returns a new list; the inputs are not modified. A merged detection keeps
    the highest confidence and records how many boxes it came from.
    """

    merged = [dict(detection) for detection in detections]

    changed = True

    while changed:
        changed = False

        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                a = _box_tuple(merged[i]["bounding_box"])
                b = _box_tuple(merged[j]["bounding_box"])

                if not _boxes_belong_together(a, b):
                    continue

                merged[i] = {
                    **merged[i],
                    "bounding_box": {
                        "x1": round(min(a[0], b[0]), 2),
                        "y1": round(min(a[1], b[1]), 2),
                        "x2": round(max(a[2], b[2]), 2),
                        "y2": round(max(a[3], b[3]), 2),
                    },
                    "confidence": max(
                        merged[i]["confidence"],
                        merged[j]["confidence"],
                    ),
                    "merged_from": (
                        merged[i].get("merged_from", 1)
                        + merged[j].get("merged_from", 1)
                    ),
                }

                del merged[j]
                changed = True
                break

            if changed:
                break

    return merged


def band_crop(image, box):
    """Crop a strip around a detector box, widened sideways and slightly taller."""

    image_height, image_width = image.shape[:2]

    x1, y1, x2, y2 = _box_tuple(box)

    width = x2 - x1
    height = y2 - y1

    left = max(0, int(x1 - BAND_SPAN * width))
    right = min(image_width, int(x2 + BAND_SPAN * width))
    top = max(0, int(y1 - BAND_VERTICAL_MARGIN * height))
    bottom = min(image_height, int(y2 + BAND_VERTICAL_MARGIN * height))

    if right - left <= 0 or bottom - top <= 0:
        return None

    return image[top:bottom, left:right]


def scene_text_candidates(reader, image):
    """
    Read every piece of text in the frame and build plate-shaped combinations.

    Adjacent fragments on the same row are joined, so "KZZ" and "901Q" read
    as separate pieces still produce KZZ901Q. Only combinations that align to
    the plate pattern cheaply are kept.

    Returns a list of (candidate, (x1, y1, x2, y2)) in original coordinates.
    """

    image_height, image_width = image.shape[:2]

    scale = min(1.0, SCENE_MAX_SIDE / max(image_height, image_width))

    work = image

    if scale < 1.0:
        work = cv2.resize(
            image,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA,
        )

    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)

    results = reader.readtext(
        gray,
        detail=1,
        paragraph=False,
        allowlist=OCR_ALLOWLIST,
        width_ths=1.5,
    )

    fragments = []

    for points, text, confidence in results:
        text = clean_text(text)

        if not text:
            continue

        xs = [point[0] for point in points]
        ys = [point[1] for point in points]

        fragments.append({
            "text": text,
            "confidence": float(confidence),
            "x1": min(xs) / scale,
            "y1": min(ys) / scale,
            "x2": max(xs) / scale,
            "y2": max(ys) / scale,
        })

    fragments.sort(key=lambda fragment: fragment["x1"])

    combinations = []

    for i, first in enumerate(fragments):
        group = [first]
        combinations.append(list(group))

        for second in fragments[i + 1:]:
            last = group[-1]

            height = max(
                last["y2"] - last["y1"],
                second["y2"] - second["y1"],
            )

            same_row = abs(
                (last["y1"] + last["y2"]) / 2
                - (second["y1"] + second["y2"]) / 2
            ) <= 0.5 * height

            close = second["x1"] - last["x2"] <= 2.0 * height

            if same_row and close:
                group.append(second)
                combinations.append(list(group))

    output = []

    for group in combinations:
        text = "".join(fragment["text"] for fragment in group)
        confidence = sum(f["confidence"] for f in group) / len(group)

        candidate = make_candidate("scene", "gray", "fragments", text, confidence)

        if candidate["corrected_text"] is None:
            continue

        if candidate["cost"] > SCENE_MAX_COST:
            continue

        box = (
            min(f["x1"] for f in group),
            min(f["y1"] for f in group),
            max(f["x2"] for f in group),
            max(f["y2"] for f in group),
        )

        output.append((candidate, box))

    return output


def decide_status(choice, registry):
    """
    FORMAT_VALIDATED requires a native, uncorrected free read that is very
    confident or confirmed by a second distinct read (a constrained read
    counts as confirmation), and nothing close behind it. A plate supported
    ONLY by constrained reads always goes to a human, because a constrained
    read matches the format by construction.
    """

    if not choice["format_valid"]:
        return "NEEDS_MANUAL_REVIEW"

    validated = (
        (
            choice["best_native_confidence"] >= HIGH_CONFIDENCE
            or choice["native_reads"] >= 2
            or (
                choice["native_reads"] >= 1
                and choice["constrained_reads"] >= 1
            )
        )
        and not choice["contested"]
    )

    if (
        validated
        and registry
        and not registry["exact_match"]
        and registry["near_matches"]
    ):
        validated = False

    return "FORMAT_VALIDATED" if validated else "NEEDS_REVIEW"


def build_entry(base_fields, choice, candidates, registry, diagnostics):
    return {
        **base_fields,
        "recognized_text": choice["text"],
        "ocr_confidence": choice["confidence"],
        "format_valid": choice["format_valid"],
        "matching_variants": choice["reads"],
        "corrections": choice["corrections"],
        "selection_tier": choice["tier"],
        "contested": choice["contested"],
        "alternatives": choice["alternatives"],
        "registry_match": registry,
        "status": decide_status(choice, registry),
        "diagnostics": diagnostics,
        "ocr_candidates": candidates,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_plate_text(
    image_bytes: bytes,
    detections: list,
    known_plates: list | None = None,
) -> dict:
    """
    Recognize plates for every detection.

    Pipeline per detection:
      1. Fragments of one plate (split boxes) are merged first.
      2. The plate is flattened and read in several ways (see sources).
      3. If nothing valid was read, a wider "band" around the box is read,
         which recovers a plate the detector only partly covered.
      4. If the frame still has no valid plate although the detector saw one,
         the whole frame is searched for plate-shaped text.

    `known_plates` is optional. When provided, each result includes a
    `registry_match` block and near-misses are forced to review.

    Every result has `diagnostics`: plain-language notes on what was tried.
    """

    image_array = np.frombuffer(
        image_bytes,
        dtype=np.uint8,
    )

    image = cv2.imdecode(
        image_array,
        cv2.IMREAD_COLOR,
    )

    if image is None:
        raise ValueError("Unable to decode evidence image.")

    reader = get_ocr_reader()

    original_count = len(detections)
    detections = merge_plate_detections(detections)

    recognized_plates = []
    skipped_regions = []

    for index, detection in enumerate(detections):

        box = detection["bounding_box"]

        diagnostics = []

        if detection.get("merged_from", 1) > 1:
            diagnostics.append(
                f"Merged {detection['merged_from']} detector boxes into one "
                "plate region (the detector had split the plate)."
            )

        # Crop only the detected number plate.
        plate_crop = crop_plate_region(
            image,
            box,
        )

        if plate_crop is None or plate_crop.size == 0:
            skipped_regions.append({
                "detection_index": index,
                "reason": "Invalid plate crop.",
            })
            continue

        crop_height, crop_width = plate_crop.shape[:2]

        if crop_width < MIN_PLATE_WIDTH or crop_height < MIN_PLATE_HEIGHT:
            skipped_regions.append({
                "detection_index": index,
                "reason": "Plate crop too small.",
                "width": crop_width,
                "height": crop_height,
            })
            continue

        aspect_ratio = crop_width / crop_height

        box_width = float(box["x2"]) - float(box["x1"])
        box_height = float(box["y2"]) - float(box["y1"])
        box_ratio = box_width / box_height if box_height > 0 else 0.0

        partial_suspect = box_ratio < PARTIAL_BOX_RATIO

        if partial_suspect:
            diagnostics.append(
                f"Detector box is {box_ratio:.2f}:1; a single-row plate is "
                f"about 4.5:1, so this box may cover only part of the plate."
            )

        # Flatten the plate using both methods; either may fail.
        face = rectify_by_face(plate_crop)
        characters = rectify_by_characters(plate_crop)

        save_debug_image(f"plate_{index}_crop.jpg", plate_crop)
        save_debug_image(f"plate_{index}_face.jpg", face)
        save_debug_image(f"plate_{index}_chars.jpg", characters)

        # The aspect ratio of an axis-aligned box is unreliable for tilted
        # plates, so a plate-shaped white face overrides the gate. A
        # characters-only rectification does not, which keeps non-plate
        # regions (headlights, grilles) from slipping through.
        if face is None and not (
            MIN_ASPECT_RATIO <= aspect_ratio <= MAX_ASPECT_RATIO
        ):
            skipped_regions.append({
                "detection_index": index,
                "reason": (
                    "Crop shape is not a single-row plate "
                    "(two-row plates are not supported yet)."
                ),
                "width": crop_width,
                "height": crop_height,
                "aspect_ratio": round(aspect_ratio, 2),
            })
            continue

        # (source name, image, free read modes, segment into characters?).
        # The whole-line mode and segmentation only make sense on rectified
        # plates; the raw crop uses fragment reads only.
        sources = []

        if face is not None:
            sources.append((
                "face_rectified",
                trim_margins(face),
                ("line", "fragments"),
                True,
            ))

        if characters is not None:
            sources.append((
                "char_rectified",
                characters,
                ("line", "fragments"),
                True,
            ))

        sources.append(("raw", plate_crop, ("fragments",), False))

        debug_prefix = f"plate_{index}" if DEBUG_DIR else None

        candidates, segmentation = collect_candidates(
            reader,
            sources,
            debug_prefix=debug_prefix,
        )

        choice = choose_plate(candidates) if candidates else None

        # Recovery 1: read a wider band when nothing valid came out.
        used_band = False

        if choice is None or not choice["format_valid"]:
            band = band_crop(image, box)

            if band is not None and band.size:
                save_debug_image(f"plate_{index}_band.jpg", band)

                band_candidates, _ = collect_candidates(
                    reader,
                    [("band", band, ("fragments",), False)],
                )

                if band_candidates:
                    candidates = candidates + band_candidates
                    used_band = True
                    choice = choose_plate(candidates)

                    diagnostics.append(
                        "No valid plate from the detector box; read a wider "
                        "band around it."
                    )

        base_fields = {
            "detection_index": index,
            "origin": "detector",
            "vehicle_plate_confidence": detection["confidence"],
            "bounding_box": box,
            "crop_dimensions": {
                "width": crop_width,
                "height": crop_height,
            },
            "rectified": face is not None or characters is not None,
            "rectification": {
                "face": face is not None,
                "characters": characters is not None,
            },
            "segmentation": segmentation,
            "used_band": used_band,
        }

        if not candidates or choice is None:
            recognized_plates.append({
                **base_fields,
                "recognized_text": None,
                "ocr_confidence": 0.0,
                "format_valid": False,
                "matching_variants": 0,
                "corrections": None,
                "selection_tier": None,
                "contested": False,
                "alternatives": [],
                "registry_match": None,
                "status": "NO_TEXT_DETECTED",
                "diagnostics": diagnostics,
                "ocr_candidates": [],
            })
            continue

        if not choice["format_valid"] and choice["text"]:
            diagnostics.append(
                f"Best read '{choice['text']}' has {len(choice['text'])} "
                "characters; a plate needs 7 (K, 2 letters, 3 digits, 1 letter)."
            )

        registry = registry_match(choice["text"], known_plates)

        recognized_plates.append(build_entry(
            base_fields,
            choice,
            candidates,
            registry,
            diagnostics,
        ))

    # Recovery 2: a plate was detected but nothing valid was read anywhere.
    if (
        SCENE_FALLBACK_ENABLED
        and original_count > 0
        and not any(plate["format_valid"] for plate in recognized_plates)
    ):
        try:
            scene = scene_text_candidates(reader, image)
        except Exception:
            logger.exception("Full-frame text search failed.")
            scene = []

        if scene:
            candidates = [candidate for candidate, _ in scene]
            choice = choose_plate(candidates)

            winning_boxes = [
                box for candidate, box in scene
                if candidate["corrected_text"] == choice["text"]
            ]

            x1, y1, x2, y2 = winning_boxes[0]

            registry = registry_match(choice["text"], known_plates)

            recognized_plates.append(build_entry(
                {
                    "detection_index": len(detections),
                    "origin": "scene_text",
                    "vehicle_plate_confidence": 0.0,
                    "bounding_box": {
                        "x1": round(x1, 2),
                        "y1": round(y1, 2),
                        "x2": round(x2, 2),
                        "y2": round(y2, 2),
                    },
                    "crop_dimensions": {
                        "width": int(x2 - x1),
                        "height": int(y2 - y1),
                    },
                    "rectified": False,
                    "rectification": {"face": False, "characters": False},
                    "segmentation": {},
                    "used_band": False,
                },
                choice,
                candidates,
                registry,
                [
                    "The detector found a plate but nothing valid could be "
                    "read from it; this result comes from searching the whole "
                    "frame for plate-shaped text."
                ],
            ))

    return {
        "ocr_engine": "EasyOCR",
        "language": "en",
        "plate_format": "K[A-Z]{2}[0-9]{3}[A-Z]",
        "plates_processed": len(recognized_plates),
        "plates_with_text": sum(
            1 for plate in recognized_plates
            if plate["recognized_text"]
        ),
        "plates_format_valid": sum(
            1 for plate in recognized_plates
            if plate["format_valid"]
        ),
        "plates_skipped": len(skipped_regions),
        "recognized_plates": recognized_plates,
        "skipped_regions": skipped_regions,
    }