import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Resident(models.Model):

    class Relationship(models.TextChoices):
        OWNER = "OWNER", "Property Owner"
        TENANT = "TENANT", "Tenant"
        FAMILY = "FAMILY", "Family Member"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="resident_profiles"
    )

    apartment = models.ForeignKey(
        "estates.Apartment",
        on_delete=models.PROTECT,
        related_name="residents"
    )

    relationship = models.CharField(
        max_length=20,
        choices=Relationship.choices,
        default=Relationship.TENANT
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    move_in_date = models.DateField(
        default=timezone.localdate
    )

    move_out_date = models.DateField(
        null=True,
        blank=True
    )

    is_primary_contact = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__email"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "apartment"],
                name="unique_resident_per_apartment"
            )
        ]
        indexes = [
            models.Index(fields=["status", "apartment"]),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.move_out_date and self.move_out_date < self.move_in_date:
            raise ValidationError({
                "move_out_date": "Move-out date cannot precede move-in date."
            })

    @property
    def estate(self):
        return self.apartment.block.estate

    def __str__(self):
        return f"{self.user.email} - {self.apartment}"
