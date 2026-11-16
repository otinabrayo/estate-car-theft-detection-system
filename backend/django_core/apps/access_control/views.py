from django.shortcuts import get_object_or_404

from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.estates.models import Estate, EstateMembership, Gate
from apps.estates.permissions import is_platform_admin

from .models import GateAccessEvent, VehicleMovementSession
from .serializers import (
    GateAccessEventSerializer,
    GateEntryRequestSerializer,
    GateExitRequestSerializer,
    VehicleMovementSessionSerializer,
)
from .services import (
    process_vehicle_entry,
    process_vehicle_exit,
)

def user_can_operate_estate(user, estate):
    if is_platform_admin(user):
        return True

    return EstateMembership.objects.filter(
        user=user,
        estate=estate,
        is_active=True,
        role__in=["ESTATE_ADMIN", "SECURITY"],
    ).exists()

class GateEntryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = GateEntryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        estate = get_object_or_404(
            Estate,
            id=data["estate"],
        )
        gate = get_object_or_404(
            Gate,
            id=data["gate"],
        )

        if not user_can_operate_estate(request.user, estate):
            raise PermissionDenied(
                "You cannot operate gates in this estate."
            )

        event = process_vehicle_entry(
            estate=estate,
            gate=gate,
            registration_number=data["registration_number"],
            visitor_pass_code=data.get("visitor_pass_code") or None,
            confidence=data.get("confidence"),
            source=data["source"],
            evidence_object_key=data.get("evidence_object_key", ""),
            idempotency_key=data.get("idempotency_key"),
            user=request.user,
        )

        response_status = (
            status.HTTP_200_OK
            if event.decision == GateAccessEvent.Decision.ALLOWED
            else status.HTTP_202_ACCEPTED
        )

        return Response(
            GateAccessEventSerializer(event).data,
            status=response_status,
        )

class GateExitAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = GateExitRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        estate = get_object_or_404(
            Estate,
            id=data["estate"],
        )
        gate = get_object_or_404(
            Gate,
            id=data["gate"],
        )

        if not user_can_operate_estate(request.user, estate):
            raise PermissionDenied(
                "You cannot operate gates in this estate."
            )

        event = process_vehicle_exit(
            estate=estate,
            gate=gate,
            registration_number=data["registration_number"],
            confidence=data.get("confidence"),
            source=data["source"],
            evidence_object_key=data.get("evidence_object_key", ""),
            idempotency_key=data.get("idempotency_key"),
            user=request.user,
        )

        response_status = (
            status.HTTP_200_OK
            if event.decision == GateAccessEvent.Decision.ALLOWED
            else status.HTTP_202_ACCEPTED
        )

        return Response(
            GateAccessEventSerializer(event).data,
            status=response_status,
        )

class VehicleMovementSessionListAPIView(generics.ListAPIView):
    serializer_class = VehicleMovementSessionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        queryset = VehicleMovementSession.objects.select_related(
            "estate",
            "vehicle",
            "visitor_pass",
            "entry_gate",
            "exit_gate",
            "entry_recorded_by",
            "exit_recorded_by",
        )

        if is_platform_admin(user):
            return queryset

        accessible_estates = EstateMembership.objects.filter(
            user=user,
            is_active=True,
            role__in=["ESTATE_ADMIN", "SECURITY"],
        ).values_list("estate_id", flat=True)

        return queryset.filter(
            estate_id__in=accessible_estates
        )

class GateAccessEventListAPIView(generics.ListAPIView):
    serializer_class = GateAccessEventSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        queryset = GateAccessEvent.objects.select_related(
            "estate",
            "gate",
            "movement_session",
            "vehicle",
            "visitor_pass",
            "recorded_by",
        )

        if is_platform_admin(user):
            return queryset

        accessible_estates = EstateMembership.objects.filter(
            user=user,
            is_active=True,
            role__in=["ESTATE_ADMIN", "SECURITY"],
        ).values_list("estate_id", flat=True)

        return queryset.filter(
            estate_id__in=accessible_estates
        )
