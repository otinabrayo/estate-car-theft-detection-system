from uuid import UUID
from typing import Any, Literal, cast

from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.estates.models import Estate, Gate
from apps.vehicles.models import Vehicle, normalize_registration
from apps.visitors.models import VisitorPass

from .authentication import InternalServiceTokenAuthentication
from .models import VehicleMovementSession


class SessionLookupQuerySerializer(serializers.Serializer):
    estate_id = serializers.UUIDField()

    registration_number = serializers.CharField(
        min_length=2,
        max_length=30,
    )

    # Optional to preserve compatibility with existing lookup requests.
    gate_id = serializers.UUIDField(required=False)

    visitor_pass_code = serializers.CharField(
        max_length=30,
        required=False,
        allow_blank=True,
    )

    direction = serializers.ChoiceField(
        choices=["ENTRY", "EXIT"],
        required=False,
        default="ENTRY",
    )


class IsInternalService(BasePermission):

    def has_permission(self, request, view) -> Literal[True]:
        if not isinstance(
            request.successful_authenticator,
            InternalServiceTokenAuthentication,
        ):
            raise PermissionDenied

        return True


class VehicleSessionLookupAPIView(APIView):

    authentication_classes = [
        InternalServiceTokenAuthentication,
    ]

    permission_classes = [
        IsInternalService,
    ]

    def get(self, request):

        query_serializer = SessionLookupQuerySerializer(
            data=request.query_params
        )

        query_serializer.is_valid(raise_exception=True)

        validated_data = cast(
            dict[str, Any], query_serializer.validated_data
        )

        estate_id = validated_data["estate_id"]

        registration = normalize_registration(
            validated_data["registration_number"]
        )

        estate = get_object_or_404(
            Estate,
            id=estate_id,
        )

        # Registered vehicle lookup.
        vehicle = Vehicle.objects.filter(
            estate=estate,
            normalized_registration=registration,
        ).first()

        # Existing open-session lookup.
        session = (
            VehicleMovementSession.objects
            .select_related(
                "vehicle",
                "visitor_pass",
                "entry_gate",
                "exit_gate",
            )
            .filter(
                estate=estate,
                vehicle_registration=registration,
                status=VehicleMovementSession.Status.OPEN,
            )
            .first()
        )

        vehicle_data = None

        if vehicle:
            vehicle_data = {
                "id": str(vehicle.id),
                "registration_number": vehicle.registration_number,
                "status": vehicle.status,
                "is_active": vehicle.is_active,
                "is_approved": (
                    vehicle.status == Vehicle.Status.APPROVED
                ),
            }

        session_data = None

        if session:
            session_data = {
                "id": str(session.id),
                "status": session.status,
                "vehicle_registration": session.vehicle_registration,
                "session_type": (
                    "REGISTERED_VEHICLE"
                    if session.vehicle is not None
                    else "VISITOR"
                ),
                "entry_gate": {
                    "id": str(session.entry_gate.id),
                    "name": session.entry_gate.name,
                },
                "entry_at": session.entry_at,
                "visitor_pass_id": (
                    str(session.visitor_pass.id)
                    if session.visitor_pass is not None
                    else None
                ),
            }

        # Gate validation is read-only.
        gate_data = None
        gate_id = validated_data.get("gate_id")
        direction = validated_data.get("direction", "ENTRY")

        if gate_id:
            gate = Gate.objects.filter(
                id=gate_id,
                estate=estate,
            ).first()

            if gate is None:
                gate_data = {
                    "exists": False,
                    "is_active": False,
                    "supports_entry": False,
                    "supports_exit": False,
                    "supports_direction": False,
                    "direction": direction,
                    "is_valid": False,
                    "reason": "Gate does not exist in this estate.",
                }
            else:
                supports_entry = gate.gate_type in [
                    Gate.GateType.ENTRY,
                    Gate.GateType.BOTH,
                ]

                supports_exit = gate.gate_type in [
                    Gate.GateType.EXIT,
                    Gate.GateType.BOTH,
                ]

                supports_direction = (
                    supports_entry
                    if direction == "ENTRY"
                    else supports_exit
                )

                gate_valid = (
                    estate.is_active
                    and gate.is_active
                    and supports_direction
                )

                if not estate.is_active:
                    gate_reason = "Estate is inactive."
                elif not gate.is_active:
                    gate_reason = "Gate is inactive."
                elif not supports_direction:
                    gate_reason = (
                        f"Gate does not support {direction.lower()}."
                    )
                else:
                    gate_reason = (
                        f"Gate is valid for {direction.lower()}."
                    )

                gate_data = {
                    "exists": True,
                    "id": str(gate.id),
                    "name": gate.name,
                    "gate_type": gate.gate_type,
                    "is_active": gate.is_active,
                    "supports_entry": supports_entry,
                    "supports_exit": supports_exit,
                    "supports_direction": supports_direction,
                    "direction": direction,
                    "is_valid": gate_valid,
                    "reason": gate_reason,
                }

        # Visitor-pass validation is also read-only.
        pass_data = {
            "supplied": False,
            "exists": False,
            "is_valid": False,
            "registration_matches": False,
            "status": None,
            "reason": "No visitor pass supplied.",
        }

        pass_code = validated_data.get("visitor_pass_code", "").strip()

        if pass_code:
            visitor_pass = (
                VisitorPass.objects
                .select_related(
                    "estate",
                    "host",
                )
                .filter(
                    estate=estate,
                    pass_code=pass_code,
                )
                .first()
            )

            pass_data["supplied"] = True

            if visitor_pass is None:
                pass_data["reason"] = (
                    "Visitor pass not found in this estate."
                )
            else:
                now = timezone.now()

                pass_registration = normalize_registration(
                    visitor_pass.vehicle_registration
                ) if visitor_pass.vehicle_registration else ""

                registration_matches = (
                    not pass_registration
                    or pass_registration == registration
                )

                pass_is_valid = visitor_pass.is_valid_at(now)

                pass_valid = (
                    pass_is_valid
                    and registration_matches
                    and estate.is_active
                )

                if not estate.is_active:
                    pass_reason = "Estate is inactive."
                elif not registration_matches:
                    pass_reason = (
                        "Visitor pass registration does not match "
                        "the detected vehicle."
                    )
                elif not pass_is_valid:
                    pass_reason = (
                        "Visitor pass is not currently valid."
                    )
                else:
                    pass_reason = "Visitor pass is valid."

                pass_data = {
                    "supplied": True,
                    "exists": True,
                    "id": str(visitor_pass.id),
                    "status": visitor_pass.status,
                    "is_valid": pass_valid,
                    "registration_matches": registration_matches,
                    "valid_from": visitor_pass.valid_from,
                    "valid_until": visitor_pass.valid_until,
                    "entries_used": visitor_pass.entries_used,
                    "max_entries": visitor_pass.max_entries,
                    "reason": pass_reason,
                }

        return Response(
            {
                "estate_id": str(estate.id),
                "estate_name": estate.name,
                "estate_is_active": estate.is_active,
                "registration_number": registration,
                "is_registered": vehicle is not None,
                "is_approved": (
                    vehicle is not None
                    and vehicle.status == Vehicle.Status.APPROVED
                ),
                "is_active": (
                    vehicle.is_active if vehicle else False
                ),
                "has_open_session": session is not None,
                "vehicle": vehicle_data,
                "movement_session": session_data,
                "gate_validation": gate_data,
                "visitor_pass_validation": pass_data,
            },
            status=status.HTTP_200_OK,
        )
