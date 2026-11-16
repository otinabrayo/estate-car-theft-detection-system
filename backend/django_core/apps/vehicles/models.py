import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def normalize_registration(value):
    """
    Normalize registration numbers by removing spaces and hyphens
    and converting to uppercase.
    """
    return re.sub(r"[\s-]+", "", value).upper()


class Vehicle(models.Model):

    class VehicleType(models.TextChoices):
        CAR = "CAR", "Car"
        SUV = "SUV", "SUV"
        PICKUP = "PICKUP", "Pickup"
        MOTORCYCLE = "MOTORCYCLE", "Motorcycle"
        VAN = "VAN", "Van"
        TRUCK = "TRUCK", "Truck"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending Approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        SUSPENDED = "SUSPENDED", "Suspended"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    estate = models.ForeignKey(
        "estates.Estate",
        on_delete=models.PROTECT,
        related_name="vehicles"
    )

    registered_by = models.ForeignKey(
        "residents.Resident",
        on_delete=models.PROTECT,
        related_name="vehicles"
    )

    registration_number = models.CharField(max_length=30)

    normalized_registration = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
        db_index=True
    )

    make = models.CharField(max_length=80)
    model = models.CharField(max_length=80)
    colour = models.CharField(max_length=50)

    year = models.PositiveSmallIntegerField(
        null=True,
        blank=True
    )

    vehicle_type = models.CharField(
        max_length=20,
        choices=VehicleType.choices,
        default=VehicleType.CAR
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_vehicles"
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["registration_number"]
        indexes = [
            models.Index(fields=["estate", "status"]),
        ]

    def clean(self):
        if (
            self.registered_by_id
            and self.estate_id
            and self.registered_by.apartment.block.estate_id != self.estate_id
        ):
            raise ValidationError(
                "The registering resident must belong to this estate."
            )

    def save(self, *args, **kwargs):
        self.registration_number = self.registration_number.strip().upper()
        self.normalized_registration = normalize_registration(
            self.registration_number
        )

        if self.status == self.Status.APPROVED and not self.approved_at:
            self.approved_at = timezone.now()

        super().save(*args, **kwargs)

    def __str__(self):
        return self.registration_number


class AuthorizedDriver(models.Model):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACTIVE = "ACTIVE", "Active"
        EXPIRED = "EXPIRED", "Expired"
        REVOKED = "REVOKED", "Revoked"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        related_name="authorized_drivers"
    )

    resident = models.ForeignKey(
        "residents.Resident",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authorized_driving_assignments"
    )

    full_name = models.CharField(max_length=150)

    phone_number = models.CharField(max_length=20)

    relationship = models.CharField(
        max_length=80,
        blank=True
    )

    valid_from = models.DateTimeField(default=timezone.now)

    valid_until = models.DateTimeField(
        null=True,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="driver_authorizations"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]
        indexes = [
            models.Index(fields=["vehicle", "status"]),
        ]

    def clean(self):
        if self.valid_until and self.valid_until <= self.valid_from:
            raise ValidationError({
                "valid_until": "Authorization must end after it begins."
            })

        if (
            self.resident_id
            and self.vehicle_id
            and self.resident.apartment.block.estate_id
            != self.vehicle.estate_id
        ):
            raise ValidationError(
                "The authorized resident must belong to the vehicle's estate."
            )

    @property
    def is_currently_valid(self):
        now = timezone.now()

        return (
            self.status == self.Status.ACTIVE
            and self.vehicle.status == Vehicle.Status.APPROVED
            and self.vehicle.is_active
            and self.valid_from <= now
            and (
                self.valid_until is None
                or self.valid_until > now
            )
        )

    def __str__(self):
        return f"{self.full_name} - {self.vehicle.registration_number}"
