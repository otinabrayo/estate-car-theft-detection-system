from rest_framework import serializers

from .models import SecurityAlert, OwnerConfirmationRequest


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


class OwnerConfirmationCreateSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    estate_id = serializers.UUIDField()
    gate_id = serializers.UUIDField()

    direction = serializers.ChoiceField(
        choices=OwnerConfirmationRequest.Direction.choices,
    )

    detected_registration = serializers.CharField(
        max_length=30,
    )

    confidence = serializers.DecimalField(
        max_digits=5,
        decimal_places=4,
        min_value=0,
        max_value=1,
    )

    risk_score = serializers.IntegerField(
        min_value=0,
        max_value=100,
    )

    request_reason = serializers.CharField(
        min_length=5,
        max_length=2000,
    )

    idempotency_key = serializers.UUIDField()

    evidence_object_key = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
    )

    metadata = serializers.DictField(
        required=False,
        default=dict,
    )


class OwnerConfirmationRequestSerializer(serializers.ModelSerializer):
    estate_name = serializers.CharField(
        source="estate.name",
        read_only=True,
    )

    gate_name = serializers.CharField(
        source="gate.name",
        read_only=True,
    )

    vehicle_registration = serializers.CharField(
        source="vehicle.registration_number",
        read_only=True,
    )

    class Meta:
        model = OwnerConfirmationRequest

        fields = [
            "id",
            "event_id",
            "estate",
            "estate_name",
            "vehicle",
            "vehicle_registration",
            "gate",
            "gate_name",
            "direction",
            "detected_registration",
            "confidence",
            "risk_score",
            "request_reason",
            "evidence_object_key",
            "status",
            "expires_at",
            "responded_at",
            "response_note",
            "created_at",
        ]

        read_only_fields = fields


class OwnerConfirmationResponseSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[
            OwnerConfirmationRequest.Status.CONFIRMED,
            OwnerConfirmationRequest.Status.REJECTED,
        ],
    )

    response_note = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
    )
