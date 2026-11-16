from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone

from apps.access_control.models import GateAccessEvent
from .models import SecurityAlert


# Rules can be adjusted as the system develops.
REPEATED_ATTEMPT_THRESHOLD = 3
REPEATED_ATTEMPT_WINDOW_MINUTES = 10


def create_alert(
    *,
    event,
    rule_code,
    severity,
    title,
    description,
    metadata=None,
):
    """
    Create one alert for a specific event and detection rule.
    """
    try:
        alert, created = SecurityAlert.objects.get_or_create(
            access_event=event,
            rule_code=rule_code,
            defaults={
                "estate": event.estate,
                "movement_session": event.movement_session,
                "severity": severity,
                "title": title,
                "description": description,
                "detected_registration": event.detected_registration,
                "metadata": metadata or {},
            },
        )
        return alert if created else alert

    except IntegrityError:
        # Protect against simultaneous event processing.
        return SecurityAlert.objects.get(
            access_event=event,
            rule_code=rule_code,
        )


def count_recent_attempts(event):
    """
    Count denied/review events for the same plate in the
    same estate within the configured time window.
    """
    if not event.detected_registration:
        return 0

    start_time = event.occurred_at - timedelta(
        minutes=REPEATED_ATTEMPT_WINDOW_MINUTES
    )

    return GateAccessEvent.objects.filter(
        estate=event.estate,
        detected_registration=event.detected_registration,
        decision__in=[
            GateAccessEvent.Decision.DENIED,
            GateAccessEvent.Decision.REVIEW,
        ],
        occurred_at__gte=start_time,
        occurred_at__lte=event.occurred_at,
    ).count()


def evaluate_gate_event(event):
    """
    Convert a gate access event into one or more security alerts.
    """
    reason = event.reason.lower()
    alerts = []

    # 1. Unknown vehicle
    if "not registered" in reason:
        alerts.append(create_alert(
            event=event,
            rule_code=SecurityAlert.RuleCode.UNKNOWN_VEHICLE,
            severity=SecurityAlert.Severity.HIGH,
            title="Unregistered vehicle attempted entry",
            description=(
                f"Vehicle {event.detected_registration} attempted "
                f"to enter {event.estate.name} without a registered "
                "vehicle record or visitor pass."
            ),
        ))

    # 2. Invalid visitor pass
    if (
        "visitor pass" in reason
        and any(word in reason for word in [
            "expired",
            "revoked",
            "exhausted",
            "not approved",
            "does not exist",
        ])
    ):
        alerts.append(create_alert(
            event=event,
            rule_code=SecurityAlert.RuleCode.INVALID_VISITOR_PASS,
            severity=SecurityAlert.Severity.HIGH,
            title="Invalid visitor pass presented",
            description=(
                f"Vehicle {event.detected_registration} presented "
                "a visitor pass that could not authorize entry."
            ),
        ))

    # 3. Plate mismatch
    if "does not match" in reason:
        alerts.append(create_alert(
            event=event,
            rule_code=SecurityAlert.RuleCode.PLATE_MISMATCH,
            severity=SecurityAlert.Severity.HIGH,
            title="Visitor vehicle plate mismatch",
            description=(
                f"Detected plate {event.detected_registration} "
                "does not match the registration stored on the "
                "visitor pass."
            ),
        ))

    # 4. Exit without entry
    if (
        event.direction == GateAccessEvent.Direction.EXIT
        and "without a matching active entry session" in reason
    ):
        alerts.append(create_alert(
            event=event,
            rule_code=SecurityAlert.RuleCode.UNMATCHED_EXIT,
            severity=SecurityAlert.Severity.CRITICAL,
            title="Vehicle exit without recorded entry",
            description=(
                f"Vehicle {event.detected_registration} attempted "
                "to exit without a matching active movement session. "
                "Security should verify the vehicle and investigate "
                "possible tailgating, missed entry recording, or "
                "unauthorized movement."
            ),
        ))

    # 5. Duplicate entry
    if "already has an open movement session" in reason:
        alerts.append(create_alert(
            event=event,
            rule_code=SecurityAlert.RuleCode.DUPLICATE_ENTRY,
            severity=SecurityAlert.Severity.HIGH,
            title="Duplicate vehicle entry attempt",
            description=(
                f"Vehicle {event.detected_registration} attempted "
                "to enter while an existing movement session "
                "was still open."
            ),
        ))

    # 6. Low ANPR confidence
    if "confidence is below" in reason:
        alerts.append(create_alert(
            event=event,
            rule_code=SecurityAlert.RuleCode.LOW_ANPR_CONFIDENCE,
            severity=SecurityAlert.Severity.MEDIUM,
            title="Low number plate recognition confidence",
            description=(
                f"The plate recognition confidence for "
                f"{event.detected_registration or 'unknown plate'} "
                "was below the configured threshold. Manual "
                "verification is required."
            ),
            metadata={
                "confidence": (
                    str(event.confidence)
                    if event.confidence is not None
                    else None
                ),
            },
        ))

    # 7. Repeated access attempts
    attempts = count_recent_attempts(event)

    if attempts >= REPEATED_ATTEMPT_THRESHOLD:
        alerts.append(create_alert(
            event=event,
            rule_code=SecurityAlert.RuleCode.REPEATED_DENIALS,
            severity=SecurityAlert.Severity.HIGH,
            title="Repeated suspicious gate access attempts",
            description=(
                f"Registration {event.detected_registration} "
                f"has generated {attempts} denied or review events "
                f"within {REPEATED_ATTEMPT_WINDOW_MINUTES} minutes."
            ),
            metadata={
                "attempt_count": attempts,
                "window_minutes": REPEATED_ATTEMPT_WINDOW_MINUTES,
            },
        ))

    return alerts
