import uuid

from django.conf import settings
from django.db import models


class SecurityAlert(models.Model):

    class RuleCode(models.TextChoices):
        UNKNOWN_VEHICLE = "UNKNOWN_VEHICLE", "Unknown vehicle"
        INVALID_VISITOR_PASS = "INVALID_VISITOR_PASS", "Invalid visitor pass"
        PLATE_MISMATCH = "PLATE_MISMATCH", "Vehicle plate mismatch"
        UNMATCHED_EXIT = "UNMATCHED_EXIT", "Unmatched vehicle exit"
        DUPLICATE_ENTRY = "DUPLICATE_ENTRY", "Duplicate vehicle entry"
        LOW_ANPR_CONFIDENCE = "LOW_ANPR_CONFIDENCE", "Low ANPR confidence"
        REPEATED_DENIALS = "REPEATED_DENIALS", "Repeated access attempts"
        SESSION_ANOMALY = "SESSION_ANOMALY", "Movement session anomaly"
        OWNER_REJECTED_VEHICLE = "OWNER_REJECTED_VEHICLE", "Owner rejected vehicle"
        OWNER_CONFIRMATION_EXPIRED = "OWNER_CONFIRMATION_EXPIRED", "Owner confirmation expired"

    class Severity(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        INVESTIGATING = "INVESTIGATING", "Under investigation"
        RESOLVED = "RESOLVED", "Resolved"
        DISMISSED = "DISMISSED", "Dismissed"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    estate = models.ForeignKey(
        "estates.Estate",
        on_delete=models.PROTECT,
        related_name="security_alerts",
    )

    access_event = models.ForeignKey(
        "access_control.GateAccessEvent",
        on_delete=models.PROTECT,
        related_name="security_alerts",
    )

    movement_session = models.ForeignKey(
        "access_control.VehicleMovementSession",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="security_alerts",
    )

    rule_code = models.CharField(
        max_length=30,
        choices=RuleCode.choices,
    )

    severity = models.CharField(
        max_length=10,
        choices=Severity.choices,
    )

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.OPEN,
    )

    title = models.CharField(max_length=200)
    description = models.TextField()

    detected_registration = models.CharField(
        max_length=20,
        blank=True,
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_security_alerts",
    )

    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_security_alerts",
    )

    acknowledged_at = models.DateTimeField(null=True, blank=True)

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_security_alerts",
    )

    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)

    dismissed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dismissed_security_alerts",
    )

    dismissed_at = models.DateTimeField(null=True, blank=True)
    dismissal_reason = models.TextField(blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["access_event", "rule_code"],
                name="one_alert_per_event_rule",
            ),
        ]
        indexes = [
            models.Index(fields=["estate", "status", "severity"]),
            models.Index(fields=["detected_registration", "created_at"]),
            models.Index(fields=["rule_code", "created_at"]),
        ]

    def __str__(self):
        return (
            f"{self.rule_code} - {self.detected_registration} "
            f"({self.severity})"
        )



class OwnerConfirmationRequest(models.Model):

    class Direction(models.TextChoices):
        ENTRY = "ENTRY", "Entry"
        EXIT = "EXIT", "Exit"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Owner Confirmed"
        REJECTED = "REJECTED", "Owner Rejected"
        EXPIRED = "EXPIRED", "Expired"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    # Recognition event that triggered this confirmation.
    # This is a correlation ID, not a GateAccessEvent FK.
    event_id = models.UUIDField(unique=True)

    estate = models.ForeignKey(
        "estates.Estate",
        on_delete=models.PROTECT,
        related_name="owner_confirmation_requests",
    )

    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="owner_confirmation_requests",
    )

    owner = models.ForeignKey(
        "residents.Resident",
        on_delete=models.PROTECT,
        related_name="vehicle_confirmation_requests",
    )

    gate = models.ForeignKey(
        "estates.Gate",
        on_delete=models.PROTECT,
        related_name="owner_confirmation_requests",
    )

    direction = models.CharField(
        max_length=5,
        choices=Direction.choices,
    )

    detected_registration = models.CharField(
        max_length=30,
    )

    confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
    )

    risk_score = models.PositiveSmallIntegerField(
        default=0,
    )

    request_reason = models.TextField()

    evidence_object_key = models.CharField(
        max_length=500,
        blank=True,
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )

    expires_at = models.DateTimeField()

    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owner_confirmation_responses",
    )

    responded_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    response_note = models.TextField(blank=True)

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    idempotency_key = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        db_index=True,
        help_text="Links this confirmation to its original gate access event.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["event_id"],
                name="unique_owner_confirmation_event",
            ),
        ]

        indexes = [
            models.Index(
                fields=["owner", "status", "expires_at"],
            ),
            models.Index(
                fields=["estate", "status", "created_at"],
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.vehicle and self.estate:
            if self.vehicle.estate != self.estate:
                raise ValidationError(
                    "Vehicle does not belong to this estate."
                )

        if self.owner and self.vehicle:
            if self.vehicle.registered_by != self.owner:
                raise ValidationError(
                    "Confirmation owner must be the registered vehicle owner."
                )

        if self.gate and self.estate:
            if self.gate.estate_id != self.estate:
                raise ValidationError(
                    "Gate does not belong to this estate."
                )

        if self.confidence is not None:
            if not 0 <= self.confidence <= 1:
                raise ValidationError(
                    "Confidence must be between 0 and 1."
                )

        if self.risk_score > 100:
            raise ValidationError(
                "Risk score cannot exceed 100."
            )

    @property
    def is_expired(self):
        from django.utils import timezone

        return (
            self.status == self.Status.PENDING
            and timezone.now() >= self.expires_at
        )

    def __str__(self):
        return (
            f"{self.detected_registration} - "
            f"{self.direction} - {self.status}"
        )
