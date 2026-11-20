
import re
from pathlib import Path

import cv2                # type: ignore
import numpy as np        # type: ignore
import pytesseract        # type: ignore

from services.vision_service.app.plate_detector import (
    detect_number_plates,
)

# Windows Tesseract executable
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

IMAGE_PATH = Path(
    "services/vision_service/tests/test_images/kdl502g.png"
)

ALLOWED_CHARACTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def normalize_text(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def preprocess_variants(crop):
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    # Upscale for small characters.
    enlarged = cv2.resize(
        gray,
        None,
        fx=3,
        fy=3,
        interpolation=cv2.INTER_CUBIC,
    )

    # Improve contrast.
    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8),
    )

    enhanced = clahe.apply(enlarged)

    # Otsu thresholding.
    _, otsu = cv2.threshold(
        enhanced,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )

    # Adaptive thresholding.
    adaptive = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        11,
    )

    return {
        "grayscale": enlarged,
        "clahe": enhanced,
        "otsu": otsu,
        "adaptive": adaptive,
    }


def run_comparison():
    if not IMAGE_PATH.exists():
        raise FileNotFoundError(
            f"Test image not found: {IMAGE_PATH}"
        )

    image_bytes = IMAGE_PATH.read_bytes()

    image = cv2.imdecode(
        np.frombuffer(image_bytes, dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )

    if image is None:
        raise ValueError("Unable to decode test image.")

    height, width = image.shape[:2]

    print(f"\nImage resolution: {width}x{height}")

    # Use the existing trained YOLO plate detector.
    detection_result = detect_number_plates(image_bytes)

    print(
        f"Detected plates: {detection_result['plate_count']}"
    )

    if not detection_result["detections"]:
        print("No plate detected. Cannot run OCR.")
        return

    configs = {
        "PSM 7": "--oem 3 --psm 7",
        "PSM 8": "--oem 3 --psm 8",
        "PSM 13": "--oem 3 --psm 13",
    }

    for index, detection in enumerate(
        detection_result["detections"]
    ):
        box = detection["bounding_box"]

        # Add a small margin around the detected plate.
        padding_x = int(
            (box["x2"] - box["x1"]) * 0.03
        )
        padding_y = int(
            (box["y2"] - box["y1"]) * 0.08
        )

        x1 = max(0, int(box["x1"]) - padding_x)
        y1 = max(0, int(box["y1"]) - padding_y)
        x2 = min(width, int(box["x2"]) + padding_x)
        y2 = min(height, int(box["y2"]) + padding_y)

        crop = image[y1:y2, x1:x2]

        if crop.size == 0:
            print(f"Detection {index}: invalid crop")
            continue

        print(f"\n{'=' * 55}")
        print(f"PLATE DETECTION {index + 1}")
        print(
            f"YOLO confidence: {detection['confidence']}"
        )

        variants = preprocess_variants(crop)

        for variant_name, processed_image in variants.items():
            for config_name, config in configs.items():

                full_config = (
                    f"{config} "
                    f"-c tessedit_char_whitelist="
                    f"{ALLOWED_CHARACTERS}"
                )

                text = pytesseract.image_to_string(
                    processed_image,
                    lang="eng",
                    config=full_config,
                )

                normalized = normalize_text(text)

                print(
                    f"{variant_name:12} | "
                    f"{config_name:7} | "
                    f"{normalized or 'NO TEXT'}"
                )


if __name__ == "__main__":
    run_comparison()
