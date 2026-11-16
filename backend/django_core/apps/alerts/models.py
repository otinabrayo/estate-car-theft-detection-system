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
