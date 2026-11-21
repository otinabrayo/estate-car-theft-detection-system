from typing import Any

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.alerts.models import SecurityAlert
from apps.estates.models import EstateMembership
from apps.estates.permissions import is_platform_admin

from .models import Incident, IncidentAlert, IncidentActivity
from .permissions import can_manage_incidents
from .serializers import (
    IncidentSerializer,
    IncidentCreateSerializer,
)

class IncidentViewSet(viewsets.ModelViewSet):
    """
    Incident management API.

    Supported operations:
    - List and retrieve incidents.
    - Create incidents.
    - Assign investigators.
    - Link security alerts.
    - Change incident status.
    - Add investigation notes.

    General update and delete operations are disabled.
    """

    permission_classes = [IsAuthenticated]

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    def get_queryset(self) -> Any:
        queryset = Incident.objects.select_related(
            "estate",
            "movement_session",
            "assigned_to",
            "created_by",
            "resolved_by",
            "closed_by",
        ).prefetch_related(
            "incident_alerts__alert",
            "activities__actor",
        )

        user = self.request.user

        if is_platform_admin(user):
            return queryset

        estate_ids = EstateMembership.objects.filter(
            user=user,
            is_active=True,
            role__in=[
                EstateMembership.Role.ESTATE_ADMIN,
                EstateMembership.Role.SECURITY,
            ],
        ).values_list("estate_id", flat=True)

        return queryset.filter(estate_id__in=estate_ids)

    def get_locked_incident(self):
        """
        Retrieve and lock an incident before modifying it.

        Must be called inside transaction.atomic().
        """
        incident = get_object_or_404(
            self.filter_queryset(
                self.get_queryset()
            ).select_for_update(of=("self",)),
            pk=self.kwargs["pk"],
        )

        self.check_object_permissions(self.request, incident)

        return incident

    def get_serializer_class(self) -> Any:
        if self.action == "create":
            return IncidentCreateSerializer

        return IncidentSerializer


    @transaction.atomic
    def perform_create(self, serializer):
        estate = serializer.validated_data["estate"]

        if not can_manage_incidents(self.request.user, estate):
            raise PermissionDenied(
                "You cannot create incidents for this estate."
            )

        incident = serializer.save(created_by=self.request.user)

        IncidentActivity.objects.create(
            incident=incident,
            actor=self.request.user,
            action=IncidentActivity.Action.CREATED,
            description="Incident created.",
        )

        if incident.assigned_to:
            IncidentActivity.objects.create(
                incident=incident,
                actor=self.request.user,
                action=IncidentActivity.Action.ASSIGNED,
                description=(
                    f"Incident assigned to {incident.assigned_to.email}."
                ),
                metadata={
                    "assigned_to": str(incident.assigned_to_id),
                },
            )
    def record_activity(
        self,
        incident,
        action,
        description,
        metadata=None,
    ):
        return IncidentActivity.objects.create(
            incident=incident,
            actor=self.request.user,
            action=action,
            description=description,
            metadata=metadata or {},
        )

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        with transaction.atomic():
            incident = self.get_locked_incident()

            user_id = request.data.get("user_id")

            if not user_id:
                raise ValidationError({
                    "user_id": "This field is required."
                })

            membership = EstateMembership.objects.filter(
                estate=incident.estate,
                user_id=user_id,
                is_active=True,
                role__in=[
                    EstateMembership.Role.ESTATE_ADMIN,
                    EstateMembership.Role.SECURITY,
                ],
            ).select_related("user").first()

            if not membership:
                raise ValidationError({
                    "user_id": (
                        "The selected user must be an active estate "
                        "administrator or security member."
                    )
                })

            incident.assigned_to = membership.user
            incident.save(update_fields=["assigned_to", "updated_at"])

            self.record_activity(
                incident,
                IncidentActivity.Action.ASSIGNED,
                f"Incident assigned to {membership.user.email}.",
                {
                    "assigned_to": str(membership.user.pk),
                },
            )

        return Response(
            IncidentSerializer(
                incident,
                context=self.get_serializer_context(),
            ).data
        )

    @action(detail=True, methods=["post"])
    def link_alert(self, request, pk=None):
        with transaction.atomic():
            incident = self.get_locked_incident()

            alert_id = request.data.get("alert_id")

            if not alert_id:
                raise ValidationError({
                    "alert_id": "This field is required."
                })

            alert = get_object_or_404(
                SecurityAlert.objects.filter(
                    estate=incident.estate,
                ),
                pk=alert_id,
            )

            if IncidentAlert.objects.filter(alert=alert).exists():
                raise ValidationError({
                    "alert_id": "This alert is already linked to an incident."
                })


            try:
                with transaction.atomic():
                    link = IncidentAlert.objects.create(
                        incident=incident,
                        alert=alert,
                        linked_by=request.user,
                    )
            except IntegrityError:
                raise ValidationError({
                    "alert_id": (
                        "This alert is already linked to an incident."
                    )
                })

            self.record_activity(
                incident,
                IncidentActivity.Action.ALERT_LINKED,
                f"Security alert {alert.id} linked to incident.",
                {
                    "alert_id": str(alert.id),
                    "rule_code": alert.rule_code,
                },
            )

        return Response(
            {
                "message": "Alert linked successfully.",
                "link_id": str(link.id),
                "incident": str(incident.id),
                "alert": str(alert.id),
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        """
        Change incident status using explicitly permitted transitions.
        """

        allowed_transitions = {
            Incident.Status.OPEN: [
                Incident.Status.INVESTIGATING,
            ],
            Incident.Status.INVESTIGATING: [
                Incident.Status.CONTAINED,
                Incident.Status.RESOLVED,
            ],
            Incident.Status.CONTAINED: [
                Incident.Status.INVESTIGATING,
                Incident.Status.RESOLVED,
            ],
            Incident.Status.RESOLVED: [
                Incident.Status.CLOSED,
            ],
            Incident.Status.CLOSED: [],
        }

        with transaction.atomic():
            incident = self.get_locked_incident()

            new_status = request.data.get("status")

            valid_statuses = [
                value for value, label in Incident.Status.choices
            ]

            if new_status not in valid_statuses:
                raise ValidationError({
                    "status": "Invalid incident status."
                })

            if new_status not in allowed_transitions[incident.status]:
                raise ValidationError({
                    "status": (
                        f"Cannot transition from {incident.status} "
                        f"to {new_status}."
                    )
                })

            old_status = incident.status
            now = timezone.now()

            if new_status == Incident.Status.RESOLVED:
                summary = request.data.get("resolution_summary", "").strip()

                if not summary:
                    raise ValidationError({
                        "resolution_summary": (
                            "A resolution summary is required."
                        )
                    })

                incident.resolution_summary = summary
                incident.resolved_by = request.user
                incident.resolved_at = now

            if new_status == Incident.Status.CLOSED:
                incident.closed_by = request.user
                incident.closed_at = now

            incident.status = new_status

            incident.save()

            action_type = IncidentActivity.Action.STATUS_CHANGED

            if new_status == Incident.Status.RESOLVED:
                action_type = IncidentActivity.Action.RESOLVED
            elif new_status == Incident.Status.CLOSED:
                action_type = IncidentActivity.Action.CLOSED

            self.record_activity(
                incident,
                action_type,
                f"Incident status changed from {old_status} to {new_status}.",
                {
                    "old_status": old_status,
                    "new_status": new_status,
                },
            )

        return Response(
            IncidentSerializer(
                incident,
                context=self.get_serializer_context(),
            ).data
        )

    @action(detail=True, methods=["post"])
    def add_note(self, request, pk=None):
        with transaction.atomic():
            incident = self.get_locked_incident()

            description = request.data.get("description", "").strip()

            if not description:
                raise ValidationError({
                    "description": "Investigation note cannot be empty."
                })

            activity = self.record_activity(
                incident,
                IncidentActivity.Action.NOTE_ADDED,
                description,
            )

        return Response(
            {
                "message": "Investigation note added.",
                "activity_id": str(activity.id),
            },
            status=status.HTTP_201_CREATED,
        )