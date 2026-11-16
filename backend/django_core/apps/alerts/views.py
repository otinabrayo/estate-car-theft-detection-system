from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.estates.models import EstateMembership
from apps.estates.permissions import is_platform_admin

from .models import SecurityAlert
from .serializers import (
    SecurityAlertSerializer,
    AlertAssignmentSerializer,
    AlertResolutionSerializer,
    AlertDismissalSerializer,
)


def can_manage_alerts(user, estate):
    if is_platform_admin(user):
        return True

    return EstateMembership.objects.filter(
        user=user,
        estate=estate,
        is_active=True,
        role__in=["ESTATE_ADMIN", "SECURITY"],
    ).exists()


class SecurityAlertViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SecurityAlertSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        queryset = SecurityAlert.objects.select_related(
            "estate",
            "access_event",
            "access_event__gate",
            "movement_session",
            "assigned_to",
            "acknowledged_by",
            "resolved_by",
            "dismissed_by",
        )

        if not is_platform_admin(user):
            estate_ids = EstateMembership.objects.filter(
                user=user,
                is_active=True,
                role__in=["ESTATE_ADMIN", "SECURITY"],
            ).values_list("estate_id", flat=True)

            queryset = queryset.filter(estate_id__in=estate_ids)

        status_filter = self.request.query_params.get("status")
        severity_filter = self.request.query_params.get("severity")
        rule_filter = self.request.query_params.get("rule_code")
        registration_filter = self.request.query_params.get("registration")

        if status_filter:
            queryset = queryset.filter(status=status_filter.upper())

        if severity_filter:
            queryset = queryset.filter(severity=severity_filter.upper())

        if rule_filter:
            queryset = queryset.filter(rule_code=rule_filter.upper())

        if registration_filter:
            queryset = queryset.filter(
                detected_registration__icontains=registration_filter.strip()
            )

        return queryset

    def check_alert_access(self, alert):
        if not can_manage_alerts(
            self.request.user,
            alert.estate,
        ):
            raise PermissionDenied(
                "You cannot manage alerts in this estate."
            )

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        alert = self.get_object()
        self.check_alert_access(alert)

        if alert.status != SecurityAlert.Status.OPEN:
            raise ValidationError(
                "Only open alerts can be acknowledged."
            )

        alert.status = SecurityAlert.Status.ACKNOWLEDGED
        alert.acknowledged_by = request.user
        alert.acknowledged_at = timezone.now()

        alert.save(update_fields=[
            "status",
            "acknowledged_by",
            "acknowledged_at",
            "updated_at",
        ])

        return Response(self.get_serializer(alert).data)

    @action(detail=True, methods=["post"])
    def investigate(self, request, pk=None):
        alert = self.get_object()
        self.check_alert_access(alert)

        if alert.status not in [
            SecurityAlert.Status.OPEN,
            SecurityAlert.Status.ACKNOWLEDGED,
        ]:
            raise ValidationError(
                "This alert cannot be moved into investigation."
            )

        alert.status = SecurityAlert.Status.INVESTIGATING

        if not alert.acknowledged_by:
            alert.acknowledged_by = request.user
            alert.acknowledged_at = timezone.now()

        alert.save(update_fields=[
            "status",
            "acknowledged_by",
            "acknowledged_at",
            "updated_at",
        ])

        return Response(self.get_serializer(alert).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        alert = self.get_object()
        self.check_alert_access(alert)

        serializer = AlertAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        assignee_id = serializer.validated_data["assigned_to"]

        membership = EstateMembership.objects.filter(
            user_id=assignee_id,
            estate=alert.estate,
            is_active=True,
            role__in=["ESTATE_ADMIN", "SECURITY"],
        ).select_related("user").first()

        if not membership:
            raise ValidationError(
                "Assignee must be active security staff or an "
                "estate administrator in this estate."
            )

        alert.assigned_to = membership.user

        if not membership and is_platform_admin(request.user):
            from django.contrib.auth import get_user_model

            User = get_user_model()
            assignee = User.objects.filter(
                id=assignee_id,
                is_active=True,
            ).first()

            if not assignee:
                raise ValidationError("Assignee does not exist or is inactive.")
        else:
            assignee = membership.user

        alert.assigned_to = assignee
        alert.save(update_fields=[
            "assigned_to",
            "updated_at",
        ])

        return Response(self.get_serializer(alert).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        alert = self.get_object()
        self.check_alert_access(alert)

        serializer = AlertResolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if alert.status not in [
            SecurityAlert.Status.ACKNOWLEDGED,
            SecurityAlert.Status.INVESTIGATING,
        ]:
            raise ValidationError(
                "Acknowledge or investigate an alert before resolving it."
            )

        alert.status = SecurityAlert.Status.RESOLVED
        alert.resolved_by = request.user
        alert.resolved_at = timezone.now()
        alert.resolution_notes = serializer.validated_data[
            "resolution_notes"
        ]

        alert.save(update_fields=[
            "status",
            "resolved_by",
            "resolved_at",
            "resolution_notes",
            "updated_at",
        ])

        return Response(self.get_serializer(alert).data)

    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None):
        alert = self.get_object()
        self.check_alert_access(alert)

        serializer = AlertDismissalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if alert.status in [
            SecurityAlert.Status.RESOLVED,
            SecurityAlert.Status.DISMISSED,
        ]:
            raise ValidationError(
                "This alert is already closed."
            )

        alert.status = SecurityAlert.Status.DISMISSED
        alert.dismissed_by = request.user
        alert.dismissed_at = timezone.now()
        alert.dismissal_reason = serializer.validated_data[
            "dismissal_reason"
        ]

        alert.save(update_fields=[
            "status",
            "dismissed_by",
            "dismissed_at",
            "dismissal_reason",
            "updated_at",
        ])

        return Response(self.get_serializer(alert).data)
