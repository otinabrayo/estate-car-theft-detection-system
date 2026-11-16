import secrets
import uuid


from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Visitor(models.Model):
    class IdentificationType(models.TextChoices):
        NATIONAL_ID = "NATIONAL_ID", "National ID"
        PASSPORT = "PASSPORT", "Passport"
        OTHER = "OTHER", "Other"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    estate = models.ForeignKey(
        "estates.Estate",
        on_delete=models.PROTECT,
        related_name="visitors",
    )

    full_name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField(blank=True)

    identification_type = models.CharField(
        max_length=20,
        choices=IdentificationType.choices,
        blank=True,
    )
    identification_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Optional reference. Avoid storing unnecessary identity data.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]
        indexes = [
            models.Index(fields=["estate", "phone_number"]),
        ]

    def __str__(self):
        return f"{self.full_name} - {self.estate.name}"


class VisitorPass(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending host approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        EXPIRED = "EXPIRED", "Expired"
        REVOKED = "REVOKED", "Revoked"
        EXHAUSTED = "EXHAUSTED", "Entries exhausted"

    id = models.UUIDField(primary_key=True, default=__import__(
        "uuid"
    ).uuid4, editable=False)

    estate = models.ForeignKey(
        "estates.Estate",
        on_delete=models.PROTECT,
        related_name="visitor_passes",
    )

    visitor = models.ForeignKey(
        Visitor,
        on_delete=models.PROTECT,
        related_name="passes",
    )

    host = models.ForeignKey(
        "residents.Resident",
        on_delete=models.PROTECT,
        related_name="visitor_passes",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_visitor_passes",
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_visitor_passes",
    )

    pass_code = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
    )

    purpose = models.CharField(max_length=255, blank=True)

    vehicle_registration = models.CharField(
        max_length=20,
        blank=True,
    )

    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField()

    max_entries = models.PositiveSmallIntegerField(default=1)
    entries_used = models.PositiveSmallIntegerField(default=0)

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
    )

    approved_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["estate", "status"]),
            models.Index(fields=["pass_code"]),
            models.Index(fields=["valid_from", "valid_until"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_entries__gte=1),
                name="visitor_pass_max_entries_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(entries_used__lte=models.F("max_entries")),
                name="visitor_pass_entries_within_limit",
            ),
        ]

    def __str__(self):
        return f"{self.visitor.full_name} - {self.pass_code}"

    def generate_pass_code(self):
        """Generate an unpredictable, unique visitor pass code."""
        while True:
            code = secrets.token_urlsafe(9).upper()

            if not VisitorPass.objects.filter(pass_code=code).exists():
                return code

    def save(self, *args, **kwargs):
        if not self.pass_code:
            self.pass_code = self.generate_pass_code()

        if self.vehicle_registration:
            self.vehicle_registration = "".join(
                self.vehicle_registration.upper().split()
            ).replace("-", "")

        super().save(*args, **kwargs)

    def clean(self):
        if self.valid_until <= self.valid_from:
            raise ValidationError(
                {"valid_until": "The end time must be after the start time."}
            )

        if self.visitor_id and self.estate_id:
            if self.visitor.estate_id != self.estate_id:
                raise ValidationError(
                    {"visitor": "Visitor must belong to this estate."}
                )

        if self.host_id and self.estate_id:
            if self.host.apartment.block.estate_id != self.estate_id:
                raise ValidationError(
                    {"host": "Host must belong to this estate."}
                )

        if self.entries_used > self.max_entries:
            raise ValidationError(
                {"entries_used": "Entries used cannot exceed the limit."}
            )

    def is_valid_at(self, moment=None):
        """Check whether the pass is currently eligible for gate entry."""
        moment = moment or timezone.now()

        return (
            self.status == self.Status.APPROVED
            and self.valid_from <= moment <= self.valid_until
            and self.entries_used < self.max_entries
            and self.estate.is_active
            and self.host.status == "ACTIVE"
        )

    def record_entry(self):
        """
        Record an authorized entry.

        Gate verification will call this inside a database transaction
        after validating the pass and preventing concurrent double-use.
        """
        if not self.is_valid_at():
            raise ValidationError("This visitor pass is not currently valid.")

        self.entries_used += 1

        if self.entries_used >= self.max_entries:
            self.status = self.Status.EXHAUSTED

        self.save(update_fields=[
            "entries_used",
            "status",
            "updated_at",
        ])
