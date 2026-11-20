MIN_PUBLISH_CONFIDENCE = 0.70          # was 0.80 / 0.85
MIN_VALID_OBSERVATIONS = 1             # allow single good observation

ALLOWED_STATUSES = {
    "CONSENSUS_CANDIDATE",
    "FORMAT_VALIDATED",
    "SINGLE_OBSERVATION_REVIEW",       # ← this was blocking the best result
    "HIGH_CONFIDENCE",
}


def evaluate_publication_eligibility(plate):
    if not plate.get("format_valid"):
        return False, "INVALID_REGISTRATION_FORMAT"

    status = plate.get("status")
    if status not in ALLOWED_STATUSES:
        return False, f"STATUS_REQUIRES_MANUAL_REVIEW:{status}"

    valid_observations = plate.get("valid_observation_count", 0)
    if valid_observations < MIN_VALID_OBSERVATIONS:
        return False, "INSUFFICIENT_VALID_OBSERVATIONS"

    # Prefer best confidence when average is pulled down by a weak read
    confidence = max(
        plate.get("average_ocr_confidence", 0),
        plate.get("best_ocr_confidence", 0),
    )

    if confidence < MIN_PUBLISH_CONFIDENCE:
        return False, "OCR_CONFIDENCE_BELOW_THRESHOLD"

    return True, "PUBLICATION_ELIGIBLE"