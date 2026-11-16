from django.utils import timezone
from rest_framework import serializers

from apps.estates.models import EstateMembership
from apps.estates.permissions import is_platform_admin, has_estate_access
from apps.residents.models import Resident
from .models import Visitor, VisitorPass


class VisitorSerializer(serializers.ModelSerializer):
    estate_name = serializers.CharField(
        source="estate.name",
        read_only=True,
    )

    class Meta:
        model = Visitor
        fields = [
            "id",
            "estate",
            "estate_name",
            "full_name",
            "phone_number",
            "email",
            "identification_type",
            "identification_reference",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        request = self.context["request"]
        estate = attrs.get("estate")

        if not estate or not estate.is_active:
            raise serializers.ValidationError(
                {"estate": "Select an active estate."}
            )

        if not is_platform_admin(request.user):
            if not has_estate_access(request.user, estate):
                raise serializers.ValidationError(
                    "You do not have active membership in this estate."
                )
                
        return attrs


class VisitorPassSerializer(serializers.ModelSerializer):
    visitor_name = serializers.CharField(
        source="visitor.full_name",
        read_only=True,
    )
    host_name = serializers.CharField(
        source="host.user.get_full_name",
        read_only=True,
    )
    host_email = serializers.EmailField(
        source="host.user.email",
        read_only=True,
    )

    class Meta:
        model = VisitorPass
        fields = [
            "id",
            "estate",
            "visitor",
            "visitor_name",
            "host",
            "host_name",
            "host_email",
            "created_by",
            "approved_by",
            "pass_code",
            "purpose",
            "vehicle_registration",
            "valid_from",
            "valid_until",
            "max_entries",
            "entries_used",
            "status",
            "approved_at",
            "revoked_at",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "created_by",
            "approved_by",
            "pass_code",
            "entries_used",
            "status",
            "approved_at",
            "revoked_at",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        request = self.context["request"]

        estate = attrs.get("estate")
        visitor = attrs.get("visitor")
        host = attrs.get("host")

        if not estate.is_active:
            raise serializers.ValidationError(
                {"estate": "This estate is inactive."}
            )

        if visitor.estate_id != estate.id:
            raise serializers.ValidationError(
                {"visitor": "Visitor does not belong to this estate."}
            )

        if host.apartment.block.estate_id != estate.id:
            raise serializers.ValidationError(
                {"host": "Host does not belong to this estate."}
            )

        if host.status != "ACTIVE":
            raise serializers.ValidationError(
                {"host": "Only active residents can host visitors."}
            )

        if attrs["valid_until"] <= attrs["valid_from"]:
            raise serializers.ValidationError(
                {"valid_until": "End time must be after start time."}
            )

        if attrs["valid_until"] <= timezone.now():
            raise serializers.ValidationError(
                {"valid_until": "A new pass must expire in the future."}
            )

        if not is_platform_admin(request.user):
            if host.user_id == request.user.id:
                pass
            else:
                allowed = EstateMembership.objects.filter(
                    user=request.user,
                    estate=estate,
                    is_active=True,
                    role__in=["ESTATE_ADMIN", "SECURITY"],
                ).exists()

                if not allowed:
                    raise serializers.ValidationError(
                        "You can only create passes for yourself, "
                        "or act as authorized estate staff."
                    )

        return attrs
