import logging
from typing import Any

import requests

from .verification_client import (
    VerificationServiceClient,
)

logger = logging.getLogger(__name__)


class EventProcessor:
    """
    Coordinates vehicle recognition event processing.

    Processing order:
        1. FastAPI verification and risk assessment.
        2. Django authoritative gate-access processing.

    Django remains responsible for creating or closing
    movement sessions and recording gate-access decisions.
    """

    def __init__(
        self,
        django_client,
        verification_client=None,
    ):
        self.django_client = django_client

        self.verification_client = (
            verification_client
            or VerificationServiceClient()
        )

    def process_event(self, event: Any) -> dict:
        """
        Process one validated GateEvent.

        Returns Django's response to preserve the existing
        consumer's expected authoritative processing result.

        Exceptions are deliberately propagated to the existing
        Kafka retry/DLQ reliability workflow.
        """

        event_id = str(event.event_id)

        logger.info(
            "Starting event processing: event_id=%s direction=%s",
            event_id,
            event.direction,
        )

        # STEP 1: Verify recognition event using FastAPI.
        verification_result = (
            self.verification_client.verify_event(event)
        )

        verification_status = verification_result[
            "verification_status"
        ]

        risk_score = verification_result["risk_score"]
        risk_level = verification_result["risk_level"]

        logger.info(
            "Verification completed: event_id=%s "
            "status=%s risk_score=%s risk_level=%s",
            event_id,
            verification_status,
            risk_score,
            risk_level,
        )

        # Record owner-confirmation activity.
        if verification_result.get(
            "owner_confirmation_required",
            False,
        ):
            logger.warning(
                "Owner confirmation requested: event_id=%s "
                "confirmation_id=%s status=%s",
                event_id,
                verification_result.get(
                    "owner_confirmation_id"
                ),
                verification_result.get(
                    "owner_confirmation_status"
                ),
            )

        # STEP 2: Django makes the authoritative decision.
        #
        # Do not skip this call based on FastAPI's ALLOW,
        # REVIEW or DENY result. Django independently checks
        # access rules and manages movement sessions.
        django_result = self.django_client.process_event(
            event
        )

        logger.info(
            "Django gate processing completed: event_id=%s "
            "result=%s",
            event_id,
            django_result,
        )

        return django_result

    def get_owner_review(self, event_id: str) -> dict:
        """
        Retrieve the latest owner response.

        This method does not authorize movement. It makes the
        owner's response available to security workflows.
        """

        try:
            result = (
                self.verification_client
                .get_owner_confirmation_status(
                    str(event_id)
                )
            )

            owner_status = result["status"]

            if owner_status == "REJECTED":
                logger.warning(
                    "SECURITY WARNING: Owner rejected vehicle "
                    "movement for event %s",
                    event_id,
                )

            elif owner_status == "CONFIRMED":
                logger.info(
                    "Owner confirmed vehicle movement "
                    "for event %s",
                    event_id,
                )

            elif owner_status == "EXPIRED":
                logger.warning(
                    "Owner confirmation expired for event %s",
                    event_id,
                )

            else:
                logger.info(
                    "Owner confirmation still pending "
                    "for event %s",
                    event_id,
                )

            return result

        except requests.RequestException:
            logger.exception(
                "Failed to retrieve owner review for event %s",
                event_id,
            )
            raise
