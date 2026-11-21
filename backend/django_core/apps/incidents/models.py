import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Incident(models.Model):

    class IncidentType(models.TextChoices):
        THEFT_SUSPECTED = "THEFT_SUSPECTED", "Suspected Theft"
        UNAUTHORIZED_ACCESS = "UNAUTHORIZED_ACCESS", "Unauthorized Access"
        SUSPICIOUS_MOVEMENT = "SUSPICIOUS_MOVEMENT", "Suspicious Movement"
        VEHICLE_TAMPERING = "VEHICLE_TAMPERING", "Vehicle Tampering"
        OTHER = "OTHER", "Other"

    class Severity(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        INVESTIGATING = "INVESTIGATING", "Investigating"
        CONTAINED = "CONTAINED", "Contained"
        RESOLVED = "RESOLVED", "Resolved"
        CLOSED = "CLOSED", "Closed"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    estate = models.ForeignKey(
        "estates.Estate",
        on_delete=models.PROTECT,
        related_name="incidents",
    )

    reference = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
    )

    incident_type = models.CharField(
        max_length=30,
        choices=IncidentType.choices,
        default=IncidentType.OTHER,
    )

    severity = models.CharField(
        max_length=10,
        choices=Severity.choices,
        default=Severity.MEDIUM,
    )

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.OPEN,
    )

    title = models.CharField(max_length=200)
    description = models.TextField()

    movement_session = models.ForeignKey(
        "access_control.VehicleMovementSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidents",
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_incidents",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_incidents",
    )

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_incidents",
    )

    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    resolution_summary = models.TextField(blank=True)

    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_incidents",
    )

    closed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["estate", "status", "severity"],
            ),
            models.Index(
                fields=["estate", "created_at"],
            ),
        ]

    def clean(self):
        errors = {}

        if self.movement_session is not None:
            if self.movement_session.estate_id != self.estate.pk:
                errors["movement_session"] = (
                    "Movement session must belong to the same estate."
                )

        if self.status == self.Status.RESOLVED:
            if not self.resolved_at or self.resolved_by is None:
                errors["status"] = (
                    "Resolved incidents require a resolver and timestamp."
                )

        if self.status == self.Status.CLOSED:
            if not self.closed_at or self.closed_by is None:
                errors["status"] = (
                    "Closed incidents require a closing user and timestamp."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"INC-{uuid.uuid4().hex[:12].upper()}"

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} - {self.title}"


class IncidentAlert(models.Model):
    """
    Associates security alerts with an incident.

    An alert can belong to only one incident.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    incident = models.ForeignKey(
        Incident,
        on_delete=models.CASCADE,
        related_name="incident_alerts",
    )

    alert = models.OneToOneField(
        "alerts.SecurityAlert",
        on_delete=models.PROTECT,
        related_name="incident_link",
    )

    linked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="incident_alert_links",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        incident_id = getattr(self, "incident_id", None)
        alert_id = getattr(self, "alert_id", None)
        if (
            incident_id
            and alert_id
            and self.incident.estate.pk != self.alert.estate_id
        ):
            raise ValidationError(
                {"alert": "Alert and incident must belong to the same estate."}
            )

    def __str__(self):
        return f"{self.incident.reference} - {self.alert.pk}"


class IncidentActivity(models.Model):
    """
    Append-only record of incident investigation activity.
    """

    class Action(models.TextChoices):
        CREATED = "CREATED", "Incident Created"
        ASSIGNED = "ASSIGNED", "Investigator Assigned"
        STATUS_CHANGED = "STATUS_CHANGED", "Status Changed"
        ALERT_LINKED = "ALERT_LINKED", "Alert Linked"
        NOTE_ADDED = "NOTE_ADDED", "Investigation Note"
        RESOLVED = "RESOLVED", "Incident Resolved"
        CLOSED = "CLOSED", "Incident Closed"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    incident = models.ForeignKey(
        Incident,
        on_delete=models.CASCADE,
        related_name="activities",
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="incident_activities",
    )

    action = models.CharField(
        max_length=20,
        choices=Action.choices,
    )

    description = models.TextField()

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["incident", "created_at"],
            ),
        ]

    def __str__(self):
        return f"{self.incident.reference} - {self.action}"
