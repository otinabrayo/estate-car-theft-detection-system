import uuid

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Estate(TimeStampedModel):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    name = models.CharField(max_length=150)

    registration_number = models.CharField(
        max_length=100,
        blank=True
    )

    address = models.TextField()
    city = models.CharField(max_length=100)
    county = models.CharField(max_length=100)
    country = models.CharField(max_length=100, default="Kenya")

    timezone = models.CharField(
        max_length=50,
        default="Africa/Nairobi"
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "city"],
                name="unique_estate_name_city"
            )
        ]

    def __str__(self):
        return self.name


class EstateMembership(TimeStampedModel):

    class Role(models.TextChoices):
        ESTATE_ADMIN = "ESTATE_ADMIN", "Estate Admin"
        SECURITY = "SECURITY", "Security Personnel"
        RESIDENT = "RESIDENT", "Resident"

    estate = models.ForeignKey(
        Estate,
        on_delete=models.CASCADE,
        related_name="memberships"
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="estate_memberships"
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["estate", "user"],
                name="unique_estate_user_membership"
            )
        ]

    def __str__(self):
        return f"{self.user.email} - {self.estate.name} ({self.role})"


class ApartmentBlock(TimeStampedModel):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    estate = models.ForeignKey(
        Estate,
        on_delete=models.CASCADE,
        related_name="apartment_blocks"
    )

    name = models.CharField(max_length=100)

    description = models.TextField(blank=True)

    number_of_floors = models.PositiveSmallIntegerField(
        default=1
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["estate", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["estate", "name"],
                name="unique_block_name_per_estate"
            )
        ]

    def __str__(self):
        return f"{self.estate.name} - {self.name}"


class Apartment(TimeStampedModel):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    block = models.ForeignKey(
        ApartmentBlock,
        on_delete=models.CASCADE,
        related_name="apartments"
    )

    unit_number = models.CharField(max_length=30)

    floor_number = models.PositiveSmallIntegerField(
        null=True,
        blank=True
    )

    bedrooms = models.PositiveSmallIntegerField(default=1)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["block", "unit_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["block", "unit_number"],
                name="unique_apartment_unit_per_block"
            )
        ]

    def __str__(self):
        return f"{self.block.name} - {self.unit_number}"


class Gate(TimeStampedModel):

    class GateType(models.TextChoices):
        ENTRY = "ENTRY", "Entry Only"
        EXIT = "EXIT", "Exit Only"
        BOTH = "BOTH", "Entry and Exit"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    estate = models.ForeignKey(
        Estate,
        on_delete=models.CASCADE,
        related_name="gates"
    )

    name = models.CharField(max_length=100)

    code = models.CharField(max_length=30)

    gate_type = models.CharField(
        max_length=10,
        choices=GateType.choices,
        default=GateType.BOTH
    )

    location_description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["estate", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["estate", "code"],
                name="unique_gate_code_per_estate"
            )
        ]

    def __str__(self):
        return f"{self.estate.name} - {self.name}"
