from datetime import timedelta
from typing import cast

from django.db import transaction
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import NotFound

from apps.estates.models import Estate, EstateMembership, Gate
from apps.estates.permissions import is_platform_admin
from apps.alerts.services import create_owner_confirmation_alert
from apps.vehicles.models import Vehicle, normalize_registration
from apps.access_control.authentication import (
    InternalServiceTokenAuthentication,
)

from .models import SecurityAlert, OwnerConfirmationRequest
from .serializers import (
    SecurityAlertSerializer,
    AlertAssignmentSerializer,
    AlertResolutionSerializer,
    AlertDismissalSerializer,
    OwnerConfirmationCreateSerializer,
    OwnerConfirmationRequestSerializer,
    OwnerConfirmationResponseSerializer,
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

def expire_owner_confirmation_if_due(
    confirmation,
    now=None,
):
    """
    Expire a locked pending confirmation and create its
    corresponding security alert when required.

    Call inside transaction.atomic() after select_for_update().
    """
    now = now or timezone.now()

    if confirmation.status != OwnerConfirmationRequest.Status.PENDING:
        return False

    if now < confirmation.expires_at:
        return False

    confirmation.status = OwnerConfirmationRequest.Status.EXPIRED

    confirmation.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    create_owner_confirmation_alert(confirmation)

    return True

class IsInternalService(BasePermission):
    """
    Allow requests authenticated using the internal service token only.
    """

    def has_permission(self, request, view) -> bool:  # pyright: ignore[reportIncompatibleMethodOverride]
        return isinstance(
            request.successful_authenticator,
            InternalServiceTokenAuthentication,
        )

class SecurityAlertViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SecurityAlertSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # pyright: ignore[reportIncompatibleMethodOverride]
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

        status_filter = self.request.GET.get("status")
        severity_filter = self.request.GET.get("severity")
        rule_filter = self.request.GET.get("rule_code")
        registration_filter = self.request.GET.get("registration")

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

        if membership:
            assignee = membership.user

        elif is_platform_admin(request.user):
            from django.contrib.auth import get_user_model

            User = get_user_model()

            assignee = User.objects.filter(
                id=assignee_id,
                is_active=True,
            ).first()

            if not assignee:
                raise ValidationError(
                    "Assignee does not exist or is inactive."
                )

        else:
            raise ValidationError(
                "Assignee must be active security staff or an "
                "estate administrator in this estate."
            )

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


class OwnerConfirmationInternalCreateAPIView(APIView):

    authentication_classes = [
        InternalServiceTokenAuthentication,
    ]

    permission_classes = [
        IsInternalService,
    ]

    def post(self, request):
        serializer = OwnerConfirmationCreateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        data: dict = serializer.validated_data    # type: ignore

        # 1. Retrieve the estate.
        try:
            estate = Estate.objects.get(
                id=data["estate_id"],
                is_active=True,
            )
        except Estate.DoesNotExist:
            raise NotFound("Estate does not exist or is inactive.")

        # 2. Retrieve the gate.
        try:
            gate = Gate.objects.get(
                id=data["gate_id"],
                estate=estate,
                is_active=True,
            )
        except Gate.DoesNotExist:
            raise NotFound(
                "Gate does not exist, is inactive, or belongs "
                "to another estate."
            )

        direction = data["direction"]

        if (
            gate.gate_type != Gate.GateType.BOTH
            and gate.gate_type != direction
        ):
            raise ValidationError(
                "Gate does not support this movement direction."
            )

        # 3. Retrieve the vehicle and its registered owner.
        try:
            vehicle = Vehicle.objects.select_related(
                "registered_by",
                "registered_by__user",
                "registered_by__apartment",
                "registered_by__apartment__block",
            ).get(
                estate=estate,
                normalized_registration=normalize_registration(
                    data["detected_registration"]
                ),
            )
        except Vehicle.DoesNotExist:
            raise NotFound(
                "No registered vehicle matches the detected registration."
            )

        if (
            vehicle.status != Vehicle.Status.APPROVED
            or not vehicle.is_active
        ):
            raise ValidationError(
                "Owner confirmation cannot be requested for "
                "an unapproved or inactive vehicle."
            )

        owner = vehicle.registered_by

        # 4. Validate the registered resident.
        if owner.status != owner.Status.ACTIVE:
            raise ValidationError(
                "The registered vehicle owner is not an active resident."
            )

        if not owner.user.is_active:
            raise ValidationError(
                "The registered owner's account is inactive."
            )

        if owner.apartment.block.estate_id != estate.id:
            raise ValidationError(
                "Vehicle owner does not belong to this estate."
            )

        # 5. Validate active estate membership.
        membership_exists = EstateMembership.objects.filter(
            estate=estate,
            user=owner.user,
            role=EstateMembership.Role.RESIDENT,
            is_active=True,
        ).exists()

        if not membership_exists:
            raise ValidationError(
                "The vehicle owner does not have an active "
                "resident membership in this estate."
            )

        # 6. Create an idempotent confirmation request.
        defaults = {
            "estate": estate,
            "vehicle": vehicle,
            "owner": owner,
            "gate": gate,
            "direction": direction,
            "detected_registration": normalize_registration(
                data["detected_registration"]
            ),
            "confidence": data["confidence"],
            "risk_score": data["risk_score"],
            "request_reason": data["request_reason"],
            "idempotency_key": data["idempotency_key"],
            "evidence_object_key": data.get(
                "evidence_object_key",
                "",
            ),
            "expires_at": timezone.now() + timedelta(minutes=5),
            "metadata": data.get("metadata", {}),
        }

        with transaction.atomic():
            confirmation, created = (
                OwnerConfirmationRequest.objects.get_or_create(
                    event_id=data["event_id"],
                    defaults=defaults,
                )
            )

        # 7. Prevent an event ID from being reused for another request.
        if not created:
            same_event = (
                confirmation.estate == estate
                and confirmation.vehicle == vehicle.id
                and confirmation.gate == gate.id
                and confirmation.owner == owner.id
                and confirmation.direction == direction
            )

            if not same_event:
                return Response(
                    {
                        "detail": (
                            "This event ID has already been used "
                            "for a different confirmation request."
                        )
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        response_serializer = OwnerConfirmationRequestSerializer(
            confirmation
        )

        return Response(
            {
                "created": created,
                "confirmation": response_serializer.data,
            },
            status=(
                status.HTTP_201_CREATED
                if created
                else status.HTTP_200_OK
            ),
        )


class OwnerConfirmationInternalStatusAPIView(APIView):
    """
    Internal endpoint for the verification service to retrieve
    an owner's response to a confirmation request.
    """

    authentication_classes = [InternalServiceTokenAuthentication]
    permission_classes = [IsInternalService]

    def get(self, request, event_id):
        with transaction.atomic():
            confirmation = (
                OwnerConfirmationRequest.objects
                .select_for_update()
                .filter(event_id=event_id)
                .first()
            )

            if confirmation is None:
                return Response(
                    {"detail": "Owner confirmation request not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Expire pending requests when their deadline passes.
            expire_owner_confirmation_if_due(confirmation)

            # Ensure rejected and expired requests have their alerts.
            if confirmation.status in [
                OwnerConfirmationRequest.Status.REJECTED,
                OwnerConfirmationRequest.Status.EXPIRED,
            ]:
                create_owner_confirmation_alert(confirmation)

        return Response({
            "id": str(confirmation.id),
            "event_id": str(confirmation.event_id),
            "status": confirmation.status,
            "expires_at": confirmation.expires_at,
            "responded_at": confirmation.responded_at,
            "response_note": confirmation.response_note,
        })


class OwnerConfirmationListAPIView(APIView):
    """
    List confirmation requests belonging to the authenticated resident.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()

        # Expire overdue requests individually while holding row locks.
        with transaction.atomic():
            overdue_confirmations = (
                OwnerConfirmationRequest.objects
                .select_for_update()
                .select_related("estate")
                .filter(
                    owner__user=request.user,
                    status=OwnerConfirmationRequest.Status.PENDING,
                    expires_at__lte=now,
                )
            )

            for confirmation in overdue_confirmations:
                expire_owner_confirmation_if_due(
                    confirmation,
                    now=now,
                )

        # Only return requests belonging to this resident,
        # with an active resident profile and estate membership.
        queryset = OwnerConfirmationRequest.objects.filter(
            owner__user=request.user,
            owner__status="ACTIVE",
            estate__memberships__user=request.user,
            estate__memberships__role=EstateMembership.Role.RESIDENT,
            estate__memberships__is_active=True,
        ).select_related(
            "estate",
            "vehicle",
            "gate",
            "owner",
        ).distinct()

        status_filter = request.query_params.get("status")

        if status_filter:
            queryset = queryset.filter(
                status=status_filter.upper()
            )

        serializer = OwnerConfirmationRequestSerializer(
            queryset,
            many=True,
        )

        return Response({
            "count": queryset.count(),
            "results": serializer.data,
        })


class OwnerConfirmationRespondAPIView(APIView):
    """
    Allow the registered vehicle owner to confirm or reject a request.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        serializer = OwnerConfirmationResponseSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        validated_data = cast(dict[str, str], serializer.validated_data)
        decision = validated_data["decision"]
        response_note = validated_data.get(
            "response_note",
            "",
        )

        with transaction.atomic():

            # Lock the request while processing the response.
            try:
                confirmation = (
                    OwnerConfirmationRequest.objects
                    .select_for_update()
                    .select_related(
                        "owner",
                        "vehicle",
                        "estate",
                    )
                    .get(
                        id=pk,
                        owner__user=request.user,
                    )
                )
            except OwnerConfirmationRequest.DoesNotExist:
                raise NotFound(
                    "Confirmation request does not exist."
                )

            # Ensure the resident is still active.
            if confirmation.owner.status != "ACTIVE":
                raise PermissionDenied(
                    "Your resident account is not active."
                )

            # Ensure estate membership is still active.
            membership_exists = EstateMembership.objects.filter(
                estate=confirmation.estate,
                user=request.user,
                role=EstateMembership.Role.RESIDENT,
                is_active=True,
            ).exists()

            if not membership_exists:
                raise PermissionDenied(
                    "You do not have active resident membership "
                    "in this estate."
                )

            # Expire overdue requests before accepting a response.
            expire_owner_confirmation_if_due(confirmation)

            # An expired request cannot be answered.
            if confirmation.status == OwnerConfirmationRequest.Status.EXPIRED:
                return Response(
                    {
                        "detail": "This confirmation request has expired.",
                        "status": confirmation.status,
                    },
                    status=status.HTTP_410_GONE,
                )

            # Prevent a second response.
            if confirmation.status != OwnerConfirmationRequest.Status.PENDING:
                raise ValidationError(
                    "This confirmation request has already been answered "
                    "or is no longer available."
                )

            # Record the owner's decision.
            confirmation.status = decision
            confirmation.responded_by = request.user
            confirmation.responded_at = timezone.now()
            confirmation.response_note = response_note

            confirmation.save(
                update_fields=[
                    "status",
                    "responded_by",
                    "responded_at",
                    "response_note",
                    "updated_at",
                ]
            )

            if confirmation.status == "REJECTED":
                create_owner_confirmation_alert(confirmation)

        return Response({
            "detail": "Your response has been recorded.",
            "confirmation": OwnerConfirmationRequestSerializer(
                confirmation
            ).data,
        })
