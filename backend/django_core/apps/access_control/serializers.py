from rest_framework import serializers

from .models import GateAccessEvent, VehicleMovementSession

class VehicleMovementSessionSerializer(serializers.ModelSerializer):
    estate_name = serializers.CharField(
        source="estate.name",
        read_only=True,
    )
    entry_gate_name = serializers.CharField(
        source="entry_gate.name",
        read_only=True,
    )
    exit_gate_name = serializers.CharField(
        source="exit_gate.name",
        read_only=True,
    )
    duration_seconds = serializers.IntegerField(read_only=True)

    class Meta:
        model = VehicleMovementSession
        fields = [
            "id",
            "estate",
            "estate_name",
            "vehicle",
            "visitor_pass",
            "vehicle_registration",
            "entry_gate",
            "entry_gate_name",
            "exit_gate",
            "exit_gate_name",
            "entry_at",
            "exit_at",
            "duration_seconds",
            "status",
            "entry_recorded_by",
            "exit_recorded_by",
            "created_at",
            "updated_at",
        ]

class GateAccessEventSerializer(serializers.ModelSerializer):
    gate_name = serializers.CharField(
        source="gate.name",
        read_only=True,
    )
    session_status = serializers.CharField(
        source="movement_session.status",
        read_only=True,
    )

    class Meta:
        model = GateAccessEvent
        fields = [
            "id",
            "idempotency_key",
            "estate",
            "gate",
            "gate_name",
            "movement_session",
            "session_status",
            "vehicle",
            "visitor_pass",
            "direction",
            "decision",
            "detected_registration",
            "confidence",
            "reason",
            "source",
            "evidence_object_key",
            "metadata",
            "recorded_by",
            "occurred_at",
            "created_at",
        ]
        read_only_fields = fields

class GateEntryRequestSerializer(serializers.Serializer):
    estate = serializers.UUIDField()
    gate = serializers.UUIDField()
    registration_number = serializers.CharField(max_length=20)
    visitor_pass_code = serializers.CharField(
        max_length=30,
        required=False,
        allow_blank=True,
    )
    confidence = serializers.DecimalField(
        max_digits=5,
        decimal_places=4,
        min_value=0,
        max_value=1,
        required=False,
    )
    source = serializers.ChoiceField(
        choices=GateAccessEvent.Source.choices,
        default=GateAccessEvent.Source.MANUAL,
    )
    evidence_object_key = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
    )
    idempotency_key = serializers.UUIDField(required=False)

class GateExitRequestSerializer(serializers.Serializer):
    estate = serializers.UUIDField()
    gate = serializers.UUIDField()
    registration_number = serializers.CharField(max_length=20)
    confidence = serializers.DecimalField(
        max_digits=5,
        decimal_places=4,
        min_value=0,
        max_value=1,
        required=False,
    )
    source = serializers.ChoiceField(
        choices=GateAccessEvent.Source.choices,
        default=GateAccessEvent.Source.MANUAL,
    )
    evidence_object_key = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
    )
    idempotency_key = serializers.UUIDField(required=False)
