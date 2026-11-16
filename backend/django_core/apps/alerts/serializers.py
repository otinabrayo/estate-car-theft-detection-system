from rest_framework import serializers

from .models import SecurityAlert


class SecurityAlertSerializer(serializers.ModelSerializer):
    estate_name = serializers.CharField(
        source="estate.name",
        read_only=True,
    )

    access_event_direction = serializers.CharField(
        source="access_event.direction",
        read_only=True,
    )

    gate_name = serializers.CharField(
        source="access_event.gate.name",
        read_only=True,
    )

    assigned_to_email = serializers.EmailField(
        source="assigned_to.email",
        read_only=True,
    )

    class Meta:
        model = SecurityAlert
        fields = [
            "id",
            "estate",
            "estate_name",
            "access_event",
            "access_event_direction",
            "gate_name",
            "movement_session",
            "rule_code",
            "severity",
            "status",
            "title",
            "description",
            "detected_registration",
            "assigned_to",
            "assigned_to_email",
            "acknowledged_by",
            "acknowledged_at",
            "resolved_by",
            "resolved_at",
            "resolution_notes",
            "dismissed_by",
            "dismissed_at",
            "dismissal_reason",
            "metadata",
            "created_at",
            "updated_at",
        ]

        read_only_fields = fields


class AlertAssignmentSerializer(serializers.Serializer):
    assigned_to = serializers.UUIDField()


class AlertResolutionSerializer(serializers.Serializer):
    resolution_notes = serializers.CharField(
        min_length=5,
        max_length=3000,
    )


class AlertDismissalSerializer(serializers.Serializer):
    dismissal_reason = serializers.CharField(
        min_length=5,
        max_length=3000,
    )
