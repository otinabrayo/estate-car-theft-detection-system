import re

from collections import Counter
from difflib import SequenceMatcher


KENYAN_PLATE_PATTERN = re.compile(
    r"^K[A-Z]{2}[0-9]{3}[A-Z]$"
)


def text_similarity(first, second):
    """Compare two OCR readings, including minor character errors."""

    return SequenceMatcher(
        None,
        first,
        second,
    ).ratio()


def get_box_center(bounding_box):
    return (
        (bounding_box["x1"] + bounding_box["x2"]) / 2,
        (bounding_box["y1"] + bounding_box["y2"]) / 2,
    )


def spatial_distance_ratio(first, second, image_width, image_height):
    """Return the distance between two plate centers as a fraction
    of the image diagonal.
    """

    first_center = get_box_center(first)
    second_center = get_box_center(second)

    dx = first_center[0] - second_center[0]
    dy = first_center[1] - second_center[1]

    diagonal = (image_width ** 2 + image_height ** 2) ** 0.5

    if diagonal == 0:
        return 1.0

    distance = (dx ** 2 + dy ** 2) ** 0.5

    return distance / diagonal


def collect_observations(frame_results):
    observations = []

    for frame in frame_results:
        for plate in frame["recognized_plates"]:

            text = plate.get("recognized_text")

            if not text:
                continue

            bounding_box = plate.get("bounding_box")

            if not bounding_box:
                continue

            observations.append({
                "frame_index": frame["frame_index"],
                "timestamp_seconds": frame["timestamp_seconds"],
                "recognized_text": text.upper(),
                "ocr_confidence": float(
                    plate.get("ocr_confidence", 0.0)
                ),
                "format_valid": bool(
                    plate.get("format_valid", False)
                ),
                "bounding_box": bounding_box,
                "image_width": frame["image_width"],
                "image_height": frame["image_height"],
            })

    return observations


def group_observations(observations):
    """
    Group similar readings from nearby frames.

    This is a lightweight association heuristic, not a full
    multi-object tracking algorithm.
    """

    tracks = []

    observations.sort(
        key=lambda item: item["timestamp_seconds"]
    )

    for observation in observations:

        best_track = None
        best_score = -1

        for track in tracks:

            previous = track["observations"][-1]

            time_gap = (
                observation["timestamp_seconds"]
                - previous["timestamp_seconds"]
            )

            # Only compare observations close in time.
            if time_gap <= 0 or time_gap > 3.0:
                continue

            # Avoid grouping two detections from the same frame.
            if (
                observation["frame_index"]
                == previous["frame_index"]
            ):
                continue

            similarity = text_similarity(
                observation["recognized_text"],
                previous["recognized_text"],
            )

            distance = spatial_distance_ratio(
                observation["bounding_box"],
                previous["bounding_box"],
                observation["image_width"],
                observation["image_height"],
            )

            # Require both text similarity and spatial proximity.
            if similarity < 0.70 or distance > 0.30:
                continue

            score = similarity + (1 - distance)

            if score > best_score:
                best_score = score
                best_track = track

        if best_track is not None:
            best_track["observations"].append(observation)
        else:
            tracks.append({
                "observations": [observation],
            })

    return tracks


def calculate_consensus(observations):
    """
    Vote character-by-character using valid seven-character
    registration candidates.

    OCR confidence supplies the vote weight. It is not treated
    as a calibrated probability of correctness.
    """

    valid_candidates = [
        item for item in observations
        if KENYAN_PLATE_PATTERN.fullmatch(
            item["recognized_text"]
        )
    ]

    if not valid_candidates:
        best = max(
            observations,
            key=lambda item: item["ocr_confidence"],
        )

        return {
            "recognized_text": best["recognized_text"],
            "format_valid": False,
            "character_agreement": 0.0,
            "consensus_method": "highest_confidence_fallback",
            "valid_observation_count": 0,
        }

    votes = []

    for position in range(7):

        position_votes: dict[str, float] = {}

        for candidate in valid_candidates:
            character = candidate["recognized_text"][position]

            # Avoid zero-weight votes.
            weight = max(
                candidate["ocr_confidence"],
                0.01,
            )

            position_votes[character] = (
                position_votes.get(character, 0.0)
                + weight
            )

        winning_character, winning_weight = max(
            position_votes.items(),
            key=lambda item: item[1],
        )

        total_weight = sum(position_votes.values())

        agreement = (
            winning_weight / total_weight
            if total_weight
            else 0.0
        )

        votes.append({
            "character": winning_character,
            "agreement": agreement,
        })

    consensus_text = "".join(
        vote["character"]
        for vote in votes
    )

    character_agreement = sum(
        vote["agreement"]
        for vote in votes
    ) / len(votes)

    return {
        "recognized_text": consensus_text,
        "format_valid": bool(
            KENYAN_PLATE_PATTERN.fullmatch(consensus_text)
        ),
        "character_agreement": round(
            character_agreement,
            4,
        ),
        "consensus_method": "weighted_character_voting",
        "valid_observation_count": len(valid_candidates),
    }


def build_plate_consensus(frame_results):
    observations = collect_observations(frame_results)

    tracks = group_observations(observations)

    consolidated = []

    for track_number, track in enumerate(tracks, start=1):
        track_observations = track["observations"]

        consensus = calculate_consensus(
            track_observations
        )

        valid_observation_count = consensus[
            "valid_observation_count"
        ]

        confidence_values = [
            item["ocr_confidence"]
            for item in track_observations
        ]

        variants = Counter(
            item["recognized_text"]
            for item in track_observations
        )

        if len(track_observations) < 2:
            status = "SINGLE_OBSERVATION_REVIEW"

        elif valid_observation_count < 2:
            status = "NEEDS_MANUAL_REVIEW"

        elif (
            consensus["format_valid"]
            and consensus["character_agreement"] >= 0.80
        ):
            status = "CONSENSUS_CANDIDATE"

        else:
            status = "NEEDS_MANUAL_REVIEW"

        consolidated.append({
            "track_id": track_number,
            "recognized_text": consensus["recognized_text"],
            "format_valid": consensus["format_valid"],
            "observation_count": len(track_observations),
            "average_ocr_confidence": round(
                sum(confidence_values)
                / len(confidence_values),
                4,
            ),
            "best_ocr_confidence": round(
                max(confidence_values),
                4,
            ),
            "character_agreement": consensus[
                "character_agreement"
            ],
            "consensus_method": consensus[
                "consensus_method"
            ],
            "observed_variants": [
                {
                    "text": text,
                    "count": count,
                }
                for text, count in variants.most_common()
            ],
            "observations": [
                {
                    "frame_index": item["frame_index"],
                    "timestamp_seconds": item[
                        "timestamp_seconds"
                    ],
                    "recognized_text": item[
                        "recognized_text"
                    ],
                    "ocr_confidence": item[
                        "ocr_confidence"
                    ],
                }
                for item in track_observations
            ],
            "status": status,
            "valid_observation_count": valid_observation_count,
        })

    return consolidated
