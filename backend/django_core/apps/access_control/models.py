import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.utils import timezone


class VehicleMovementSession(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Vehicle inside estate"
        CLOSED = "CLOSED", "Vehicle exited"
        FLAGGED = "FLAGGED", "Flagged for investigation"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    estate = models.ForeignKey(
        "estates.Estate",
        on_delete=models.PROTECT,
        related_name="movement_sessions",
    )

    # Exactly one of these two must be populated.
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movement_sessions",
    )

    visitor_pass = models.ForeignKey(
        "visitors.VisitorPass",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movement_sessions",
    )

    # Snapshot captured at entry, retained for audit history.
    vehicle_registration = models.CharField(max_length=20)

    entry_gate = models.ForeignKey(
        "estates.Gate",
        on_delete=models.PROTECT,
        related_name="vehicle_entries",
    )

    exit_gate = models.ForeignKey(
        "estates.Gate",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="vehicle_exits",
    )

    entry_at = models.DateTimeField(default=timezone.now)
    exit_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
    )

    entry_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_vehicle_entries",
    )

    exit_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recorded_vehicle_exits",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-entry_at"]
        indexes = [
            models.Index(fields=["estate", "status"]),
            models.Index(fields=["vehicle_registration", "status"]),
            models.Index(fields=["entry_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(vehicle__isnull=False, visitor_pass__isnull=True)
                    | Q(vehicle__isnull=True, visitor_pass__isnull=False)
                ),
                name="session_has_one_authorization_source",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="OPEN", exit_at__isnull=True)
                    | Q(status="CLOSED", exit_at__isnull=False)
                    | Q(status="FLAGGED")
                ),
                name="session_status_matches_exit_time",
            ),
            models.UniqueConstraint(
                fields=["estate", "vehicle"],
                condition=Q(status="OPEN", vehicle__isnull=False),
                name="one_open_session_per_registered_vehicle",
            ),
            models.UniqueConstraint(
                fields=["estate", "visitor_pass"],
                condition=Q(status="OPEN", visitor_pass__isnull=False),
                name="one_open_session_per_visitor_pass",
            ),
        ]

    def __str__(self):
        return (
            f"{self.vehicle_registration} - "
            f"{self.status} - {self.entry_at}"
        )

    @property
    def duration_seconds(self):
        end_time = self.exit_at or timezone.now()
        return max(0, int((end_time - self.entry_at).total_seconds()))


class GateAccessEvent(models.Model):
    class Direction(models.TextChoices):
        ENTRY = "ENTRY", "Entry"
        EXIT = "EXIT", "Exit"

    class Decision(models.TextChoices):
        ALLOWED = "ALLOWED", "Allowed"
        DENIED = "DENIED", "Denied"
        REVIEW = "REVIEW", "Manual review required"

    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Manual security entry"
        ANPR = "ANPR", "Automatic number plate recognition"
        API = "API", "External system"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    # Optional idempotency key supplied by a camera or external client.
    idempotency_key = models.UUIDField(
        unique=True,
        null=True,
        blank=True,
    )

    estate = models.ForeignKey(
        "estates.Estate",
        on_delete=models.PROTECT,
        related_name="access_events",
    )

    gate = models.ForeignKey(
        "estates.Gate",
        on_delete=models.PROTECT,
        related_name="access_events",
    )

    movement_session = models.ForeignKey(
        VehicleMovementSession,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="access_events",
    )

    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="access_events",
    )

    visitor_pass = models.ForeignKey(
        "visitors.VisitorPass",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="access_events",
    )

    direction = models.CharField(
        max_length=5,
        choices=Direction.choices,
    )

    decision = models.CharField(
        max_length=7,
        choices=Decision.choices,
    )

    detected_registration = models.CharField(
        max_length=20,
        blank=True,
    )

    confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )

    reason = models.CharField(max_length=255)

    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.MANUAL,
    )

    # Store MinIO object keys here, not image/video binaries.
    evidence_object_key = models.CharField(
        max_length=500,
        blank=True,
    )

    metadata = models.JSONField(default=dict, blank=True)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_gate_events",
    )

    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["estate", "occurred_at"]),
            models.Index(fields=["gate", "occurred_at"]),
            models.Index(fields=["detected_registration", "occurred_at"]),
            models.Index(fields=["decision", "occurred_at"]),
        ]

    def __str__(self):
        return (
            f"{self.direction} - {self.detected_registration} - "
            f"{self.decision}"
        )
