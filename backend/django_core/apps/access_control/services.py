from decimal import Decimal

from django.db import transaction, IntegrityError
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.estates.models import Gate
from apps.vehicles.models import Vehicle, normalize_registration
from apps.visitors.models import VisitorPass

from .models import (
    GateAccessEvent,
    VehicleMovementSession,
)


MINIMUM_PLATE_CONFIDENCE = Decimal("0.8500")


def normalize_plate(value):
    return normalize_registration(value or "")


def validate_gate(gate, estate, direction):
    if not gate.is_active or not estate.is_active:
        raise ValidationError("The gate or estate is inactive.")

    if gate.estate_id != estate.id:
        raise ValidationError("Gate does not belong to this estate.")

    if gate.gate_type not in [direction, "BOTH"]:
        raise ValidationError(
            f"This gate is not configured for {direction.lower()}."
        )


def record_event(
    *,
    estate,
    gate,
    direction,
    decision,
    reason,
    user,
    registration="",
    confidence=None,
    source="MANUAL",
    movement_session=None,
    vehicle=None,
    visitor_pass=None,
    evidence_object_key="",
    metadata=None,
    idempotency_key=None,
):
    event = GateAccessEvent.objects.create(
        estate=estate,
        gate=gate,
        direction=direction,
        decision=decision,
        reason=reason,
        recorded_by=user,
        detected_registration=registration,
        confidence=confidence,
        source=source,
        movement_session=movement_session,
        vehicle=vehicle,
        visitor_pass=visitor_pass,
        evidence_object_key=evidence_object_key,
        metadata=metadata or {},
        idempotency_key=idempotency_key,
    )

    # Run the detection engine after the event is persisted.
    from apps.alerts.engine import evaluate_gate_event

    evaluate_gate_event(event)

    return event


@transaction.atomic
def process_vehicle_entry(
    *,
    estate,
    gate,
    registration_number,
    user,
    visitor_pass_code=None,
    confidence=None,
    source="MANUAL",
    evidence_object_key="",
    idempotency_key=None,
):
    direction = GateAccessEvent.Direction.ENTRY

    validate_gate(gate, estate, direction)

    registration = normalize_plate(registration_number)

    if not registration:
        raise ValidationError("A vehicle registration number is required.")

    if idempotency_key:
        existing_event = GateAccessEvent.objects.filter(
            idempotency_key=idempotency_key,
            estate=estate,
            gate=gate,
            direction=direction,
        ).first()

        if existing_event:
            return existing_event

    if confidence is not None:
        confidence = Decimal(str(confidence))

        if confidence < 0 or confidence > 1:
            raise ValidationError(
                {"confidence": "Confidence must be between 0 and 1."}
            )

        if confidence < MINIMUM_PLATE_CONFIDENCE:
            return record_event(
                estate=estate,
                gate=gate,
                direction=direction,
                decision=GateAccessEvent.Decision.REVIEW,
                reason="Plate recognition confidence is below the required threshold.",
                user=user,
                registration=registration,
                confidence=confidence,
                source=source,
                evidence_object_key=evidence_object_key,
                idempotency_key=idempotency_key,
            )

    # First check for an approved registered estate vehicle.
    vehicle = Vehicle.objects.select_for_update().filter(
        estate=estate,
        normalized_registration=registration,
        is_active=True,
        status=Vehicle.Status.APPROVED,
    ).first()

    visitor_pass = None

    if vehicle:
        # A registered vehicle must not also be treated as a visitor.
        existing_session = VehicleMovementSession.objects.filter(
            estate=estate,
            vehicle=vehicle,
            status=VehicleMovementSession.Status.OPEN,
        ).first()

        if existing_session:
            return record_event(
                estate=estate,
                gate=gate,
                direction=direction,
                decision=GateAccessEvent.Decision.REVIEW,
                reason="Vehicle already has an open movement session.",
                user=user,
                registration=registration,
                confidence=confidence,
                source=source,
                vehicle=vehicle,
                movement_session=existing_session,
                evidence_object_key=evidence_object_key,
                idempotency_key=idempotency_key,
            )

    else:
        # Unregistered vehicles require a visitor pass.
        if not visitor_pass_code:
            return record_event(
                estate=estate,
                gate=gate,
                direction=direction,
                decision=GateAccessEvent.Decision.DENIED,
                reason="Vehicle is not registered and no visitor pass was supplied.",
                user=user,
                registration=registration,
                confidence=confidence,
                source=source,
                evidence_object_key=evidence_object_key,
                idempotency_key=idempotency_key,
            )

        visitor_pass = VisitorPass.objects.select_for_update().filter(
            pass_code=visitor_pass_code,
            estate=estate,
        ).select_related(
            "visitor",
            "host",
            "host__apartment",
            "host__apartment__block",
        ).first()

        if not visitor_pass:
            return record_event(
                estate=estate,
                gate=gate,
                direction=direction,
                decision=GateAccessEvent.Decision.DENIED,
                reason="Visitor pass does not exist in this estate.",
                user=user,
                registration=registration,
                confidence=confidence,
                source=source,
                evidence_object_key=evidence_object_key,
                idempotency_key=idempotency_key,
            )

        # If the pass specifies a vehicle, require an exact plate match.
        if (
            visitor_pass.vehicle_registration
            and normalize_plate(visitor_pass.vehicle_registration) != registration
        ):
            return record_event(
                estate=estate,
                gate=gate,
                direction=direction,
                decision=GateAccessEvent.Decision.DENIED,
                reason="Vehicle registration does not match the visitor pass.",
                user=user,
                registration=registration,
                confidence=confidence,
                source=source,
                visitor_pass=visitor_pass,
                evidence_object_key=evidence_object_key,
                idempotency_key=idempotency_key,
            )

        if not visitor_pass.is_valid_at():
            return record_event(
                estate=estate,
                gate=gate,
                direction=direction,
                decision=GateAccessEvent.Decision.DENIED,
                reason="Visitor pass is expired, revoked, exhausted, or not approved.",
                user=user,
                registration=registration,
                confidence=confidence,
                source=source,
                visitor_pass=visitor_pass,
                evidence_object_key=evidence_object_key,
                idempotency_key=idempotency_key,
            )

        existing_session = VehicleMovementSession.objects.filter(
            estate=estate,
            visitor_pass=visitor_pass,
            status=VehicleMovementSession.Status.OPEN,
        ).first()

        if existing_session:
            return record_event(
                estate=estate,
                gate=gate,
                direction=direction,
                decision=GateAccessEvent.Decision.REVIEW,
                reason="Visitor pass already has an open movement session.",
                user=user,
                registration=registration,
                confidence=confidence,
                source=source,
                visitor_pass=visitor_pass,
                movement_session=existing_session,
                evidence_object_key=evidence_object_key,
                idempotency_key=idempotency_key,
            )

        # Consume one entry while holding the visitor-pass row lock.
        visitor_pass.entries_used += 1

        if visitor_pass.entries_used >= visitor_pass.max_entries:
            visitor_pass.status = VisitorPass.Status.EXHAUSTED

        visitor_pass.save(update_fields=[
            "entries_used",
            "status",
            "updated_at",
        ])

    try:
        session = VehicleMovementSession.objects.create(
            estate=estate,
            vehicle=vehicle,
            visitor_pass=visitor_pass,
            vehicle_registration=registration,
            entry_gate=gate,
            entry_at=timezone.now(),
            status=VehicleMovementSession.Status.OPEN,
            entry_recorded_by=user,
        )
    except IntegrityError:
        # A concurrent request may have created the session.
        return record_event(
            estate=estate,
            gate=gate,
            direction=direction,
            decision=GateAccessEvent.Decision.REVIEW,
            reason="Concurrent entry detected; security review is required.",
            user=user,
            registration=registration,
            confidence=confidence,
            source=source,
            vehicle=vehicle,
            visitor_pass=visitor_pass,
            evidence_object_key=evidence_object_key,
            idempotency_key=idempotency_key,
        )

    return record_event(
        estate=estate,
        gate=gate,
        direction=direction,
        decision=GateAccessEvent.Decision.ALLOWED,
        reason="Vehicle entry authorized.",
        user=user,
        registration=registration,
        confidence=confidence,
        source=source,
        movement_session=session,
        vehicle=vehicle,
        visitor_pass=visitor_pass,
        evidence_object_key=evidence_object_key,
        idempotency_key=idempotency_key,
    )


@transaction.atomic
def process_vehicle_exit(
    *,
    estate,
    gate,
    registration_number,
    user,
    confidence=None,
    source="MANUAL",
    evidence_object_key="",
    idempotency_key=None,
):
    direction = GateAccessEvent.Direction.EXIT

    validate_gate(gate, estate, direction)

    registration = normalize_plate(registration_number)

    if not registration:
        raise ValidationError("A vehicle registration number is required.")

    if idempotency_key:
        existing_event = GateAccessEvent.objects.filter(
            idempotency_key=idempotency_key
        ).first()

        if existing_event:
            return existing_event

    if confidence is not None:
        confidence = Decimal(str(confidence))

        if confidence < 0 or confidence > 1:
            raise ValidationError(
                {"confidence": "Confidence must be between 0 and 1."}
            )

        if confidence < MINIMUM_PLATE_CONFIDENCE:
            return record_event(
                estate=estate,
                gate=gate,
                direction=direction,
                decision=GateAccessEvent.Decision.REVIEW,
                reason="Exit plate recognition confidence is below the required threshold.",
                user=user,
                registration=registration,
                confidence=confidence,
                source=source,
                evidence_object_key=evidence_object_key,
                idempotency_key=idempotency_key,
            )

    session = VehicleMovementSession.objects.select_for_update(of=("self", )).filter(
        estate=estate,
        vehicle_registration=registration,
        status=VehicleMovementSession.Status.OPEN,
    ).select_related("vehicle", "visitor_pass").first()

    if not session:
        return record_event(
            estate=estate,
            gate=gate,
            direction=direction,
            decision=GateAccessEvent.Decision.REVIEW,
            reason="Exit attempted without a matching active entry session.",
            user=user,
            registration=registration,
            confidence=confidence,
            source=source,
            evidence_object_key=evidence_object_key,
        )

    # A valid recorded entry allows the vehicle to leave, even if its
    # authorization was subsequently suspended. Record the exit.
    now = timezone.now()

    session.exit_gate = gate
    session.exit_at = now
    session.exit_recorded_by = user
    session.status = VehicleMovementSession.Status.CLOSED

    session.save(update_fields=[
        "exit_gate",
        "exit_at",
        "exit_recorded_by",
        "status",
        "updated_at",
    ])

    return record_event(
        estate=estate,
        gate=gate,
        direction=direction,
        decision=GateAccessEvent.Decision.ALLOWED,
        reason="Exit matched an active movement session.",
        user=user,
        registration=registration,
        confidence=confidence,
        source=source,
        movement_session=session,
        vehicle=session.vehicle,
        visitor_pass=session.visitor_pass,
        evidence_object_key=evidence_object_key,
        idempotency_key=idempotency_key,
    )
