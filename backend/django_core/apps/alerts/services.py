import logging

from django.db import transaction

from apps.access_control.models import GateAccessEvent
from apps.alerts.models import (
    OwnerConfirmationRequest,
    SecurityAlert,
)

logger = logging.getLogger(__name__)


def create_owner_confirmation_alert(
    confirmation: OwnerConfirmationRequest,
):
    """
    Create an idempotent SecurityAlert for an owner
    rejection or a sufficiently high-risk expiration.

    Django's GateAccessEvent is the authoritative link
    between the recognition event and the alert.
    """

    if confirmation.status == "REJECTED":
        rule_code = "OWNER_REJECTED_VEHICLE"
        severity = "CRITICAL"

        title = "Vehicle rejected by registered owner"

        description = (
            f"The registered owner rejected the "
            f"{confirmation.direction.lower()} movement "
            f"of vehicle {confirmation.detected_registration}. "
            "Security personnel must investigate this event."
        )

    elif (
        confirmation.status == "EXPIRED"
        and confirmation.risk_score >= 50
    ):
        rule_code = "OWNER_CONFIRMATION_EXPIRED"
        severity = "HIGH"

        title = "High-risk owner confirmation expired"

        description = (
            f"Owner confirmation for vehicle "
            f"{confirmation.detected_registration} expired "
            "without a response. The event requires security review."
        )

    else:
        return None

    with transaction.atomic():
        access_event = (
            GateAccessEvent.objects
            .select_for_update()
            .filter(
                idempotency_key=confirmation.idempotency_key,
                estate_id=confirmation.estate.id,
            )
            .first()
        )

        if access_event is None:
            logger.warning(
                "Cannot create owner confirmation alert yet. "
                "No GateAccessEvent found for confirmation %s",
                confirmation.id,
            )
            return None

        alert, created = SecurityAlert.objects.get_or_create(
            access_event=access_event,
            rule_code=rule_code,
            defaults={
                "estate": confirmation.estate,
                "movement_session": access_event.movement_session,
                "severity": severity,
                "status": "OPEN",
                "title": title,
                "description": description,
                "detected_registration": (
                    confirmation.detected_registration
                ),
                "metadata": {
                    "source": "OWNER_CONFIRMATION",
                    "owner_confirmation_id": str(confirmation.id),
                    "recognition_event_id": str(
                        confirmation.event_id
                    ),
                    "idempotency_key": str(
                        confirmation.idempotency_key
                    ),
                    "direction": confirmation.direction,
                    "risk_score": confirmation.risk_score,
                    "owner_confirmation_status": confirmation.status,
                    "gate_id": str(confirmation.gate_id),  # type: ignore
                    "vehicle_id": str(confirmation.vehicle_id),  # type: ignore
                },
            },
        )

        if created:
            logger.warning(
                "Created %s security alert %s for confirmation %s",
                rule_code,
                alert.id,
                confirmation.id,
            )
        else:
            logger.info(
                "Security alert %s already exists for confirmation %s",
                alert.id,
                confirmation.id,
            )

        return alert
