from rest_framework import serializers

from apps.estates.models import EstateMembership
from .models import Incident, IncidentAlert, IncidentActivity


class IncidentActivitySerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(
        source="actor.email",
        read_only=True,
    )

    class Meta:
        model = IncidentActivity
        fields = [
            "id",
            "actor",
            "actor_email",
            "action",
            "description",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields


class IncidentAlertSerializer(serializers.ModelSerializer):
    alert_details = serializers.SerializerMethodField()

    class Meta:
        model = IncidentAlert
        fields = [
            "id",
            "incident",
            "alert",
            "linked_by",
            "created_at",
            "alert_details",
        ]
        read_only_fields = fields

    def get_alert_details(self, obj):
        alert = obj.alert

        return {
            "id": str(alert.id),
            "title": alert.title,
            "rule_code": alert.rule_code,
            "severity": alert.severity,
            "status": alert.status,
            "detected_registration": alert.detected_registration,
        }


class IncidentSerializer(serializers.ModelSerializer):
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    assigned_to_email = serializers.EmailField(
        source="assigned_to.email",
        read_only=True,
    )
    created_by_email = serializers.EmailField(
        source="created_by.email",
        read_only=True,
    )
    alerts = serializers.SerializerMethodField()
    activities = IncidentActivitySerializer(many=True, read_only=True)

    class Meta:
        model = Incident
        fields = [
            "id",
            "reference",
            "estate",
            "incident_type",
            "severity",
            "status",
            "title",
            "description",
            "movement_session",
            "assigned_to",
            "assigned_to_email",
            "created_by",
            "created_by_email",
            "resolved_by",
            "resolved_at",
            "resolution_summary",
            "closed_by",
            "closed_at",
            "alerts",
            "activities",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "reference",
            "status",
            "created_by",
            "resolved_by",
            "resolved_at",
            "closed_by",
            "closed_at",
            "alerts",
            "activities",
            "created_at",
            "updated_at",
        ]

    def get_alerts(self, obj):
        return IncidentAlertSerializer(
            obj.incident_alerts.select_related("alert", "linked_by"),
            many=True,
        ).data

    def validate(self, attrs):
        estate = attrs.get("estate")

        if estate and not estate.is_active:
            raise serializers.ValidationError({
                "estate": "Cannot create incidents for an inactive estate."
            })

        movement_session = attrs.get("movement_session")

        if movement_session and estate:
            if movement_session.estate_id != estate.id:
                raise serializers.ValidationError({
                    "movement_session": (
                        "Movement session must belong to the selected estate."
                    )
                })

        return attrs


class IncidentCreateSerializer(IncidentSerializer):
    """
    Separate creation serializer so clients cannot supply lifecycle fields.
    """

    class Meta(IncidentSerializer.Meta):
        fields = [
            "id",
            "reference",
            "estate",
            "incident_type",
            "severity",
            "title",
            "description",
            "movement_session",
            "assigned_to",
            "created_by",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "reference",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_assigned_to(self, user):
        initial_data = getattr(self, "initial_data", {})
        estate = initial_data.get("estate") if isinstance(initial_data, dict) else None

        if not estate:
            return user

        membership = EstateMembership.objects.filter(
            estate_id=estate,
            user=user,
            is_active=True,
            role__in=[
                EstateMembership.Role.ESTATE_ADMIN,
                EstateMembership.Role.SECURITY,
            ],
        ).exists()

        if not membership:
            raise serializers.ValidationError(
                "Assignee must be an active estate administrator or security member."
            )

        return user
