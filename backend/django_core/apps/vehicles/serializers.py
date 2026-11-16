
from rest_framework import serializers

from .models import Vehicle, AuthorizedDriver, normalize_registration


class VehicleSerializer(serializers.ModelSerializer):
    estate_name = serializers.CharField(
        source="estate.name",
        read_only=True
    )

    resident_email = serializers.EmailField(
        source="registered_by.user.email",
        read_only=True
    )

    class Meta:
        model = Vehicle
        fields = [
            "id",
            "estate",
            "estate_name",
            "registered_by",
            "resident_email",
            "registration_number",
            "normalized_registration",
            "make",
            "model",
            "colour",
            "year",
            "vehicle_type",
            "status",
            "approved_by",
            "approved_at",
            "is_active",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "normalized_registration",
            "status",
            "approved_by",
            "approved_at",
            "created_at",
            "updated_at",
        ]

    def validate_registration_number(self, value):
        normalized = normalize_registration(value)

        if not normalized:
            raise serializers.ValidationError(
                "Registration number is required."
            )

        queryset = Vehicle.objects.filter(
            normalized_registration=normalized
        )

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "This vehicle registration is already registered."
            )

        return value.strip().upper()

    def validate(self, attrs):
        estate = attrs.get(
            "estate",
            getattr(self.instance, "estate", None)
        )

        resident = attrs.get(
            "registered_by",
            getattr(self.instance, "registered_by", None)
        )

        if estate and resident:
            if resident.apartment.block.estate_id != estate.id:
                raise serializers.ValidationError(
                    "The resident must belong to the selected estate."
                )

        return attrs


class AuthorizedDriverSerializer(serializers.ModelSerializer):
    vehicle_registration = serializers.CharField(
        source="vehicle.registration_number",
        read_only=True
    )

    class Meta:
        model = AuthorizedDriver
        fields = [
            "id",
            "vehicle",
            "vehicle_registration",
            "resident",
            "full_name",
            "phone_number",
            "relationship",
            "valid_from",
            "valid_until",
            "status",
            "authorized_by",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "status",
            "authorized_by",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        vehicle = attrs.get(
            "vehicle",
            getattr(self.instance, "vehicle", None)
        )

        resident = attrs.get(
            "resident",
            getattr(self.instance, "resident", None)
        )

        valid_from = attrs.get(
            "valid_from",
            getattr(self.instance, "valid_from", None)
        )

        valid_until = attrs.get(
            "valid_until",
            getattr(self.instance, "valid_until", None)
        )

        if valid_until and valid_from and valid_until <= valid_from:
            raise serializers.ValidationError(
                "Authorization end must be after its start."
            )

        if (
            vehicle
            and vehicle.status != Vehicle.Status.APPROVED
        ):
            raise serializers.ValidationError(
                "Drivers can only be assigned to approved vehicles."
            )

        if resident and vehicle:
            if resident.apartment.block.estate_id != vehicle.estate_id:
                raise serializers.ValidationError(
                    "Resident and vehicle must belong to the same estate."
                )

        return attrs
