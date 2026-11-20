import unittest

from services.vision_service.app.publication_policy import (
    evaluate_publication_eligibility,
)


class PublicationPolicyTests(unittest.TestCase):

    def make_plate(self, **overrides):
        plate = {
            "recognized_text": "KZZ901Q",
            "format_valid": True,
            "status": "CONSENSUS_CANDIDATE",
            "valid_observation_count": 2,
            "average_ocr_confidence": 0.90,
        }

        plate.update(overrides)
        return plate

    def test_accepts_strong_consensus(self):
        eligible, reason = evaluate_publication_eligibility(
            self.make_plate()
        )

        self.assertTrue(eligible)
        self.assertEqual(reason, "PUBLICATION_ELIGIBLE")

    def test_rejects_invalid_registration_format(self):
        eligible, reason = evaluate_publication_eligibility(
            self.make_plate(format_valid=False)
        )

        self.assertFalse(eligible)
        self.assertEqual(reason, "INVALID_REGISTRATION_FORMAT")

    def test_rejects_single_observation(self):
        eligible, reason = evaluate_publication_eligibility(
            self.make_plate(
                status="SINGLE_OBSERVATION_REVIEW",
                valid_observation_count=1,
            )
        )

        self.assertFalse(eligible)
        self.assertEqual(
            reason,
            "CONSENSUS_REQUIRES_MANUAL_REVIEW",
        )

    def test_rejects_manual_review_candidate(self):
        eligible, reason = evaluate_publication_eligibility(
            self.make_plate(status="NEEDS_MANUAL_REVIEW")
        )

        self.assertFalse(eligible)
        self.assertEqual(
            reason,
            "CONSENSUS_REQUIRES_MANUAL_REVIEW",
        )

    def test_rejects_low_confidence_consensus(self):
        eligible, reason = evaluate_publication_eligibility(
            self.make_plate(average_ocr_confidence=0.6649)
        )

        self.assertFalse(eligible)
        self.assertEqual(
            reason,
            "OCR_CONFIDENCE_BELOW_THRESHOLD",
        )

    def test_accepts_confidence_at_threshold(self):
        eligible, reason = evaluate_publication_eligibility(
            self.make_plate(average_ocr_confidence=0.85)
        )

        self.assertTrue(eligible)
        self.assertEqual(reason, "PUBLICATION_ELIGIBLE")

    def test_rejects_insufficient_valid_observations(self):
        eligible, reason = evaluate_publication_eligibility(
            self.make_plate(valid_observation_count=1)
        )

        self.assertFalse(eligible)
        self.assertEqual(
            reason,
            "INSUFFICIENT_VALID_OBSERVATIONS",
        )


if __name__ == "__main__":
    unittest.main()
    