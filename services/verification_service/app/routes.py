from decimal import Decimal
from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status  # type: ignore

from .config import settings
from .django_client import (
    DjangoServiceError,
    lookup_vehicle_session,
    create_owner_confirmation_request,
    get_owner_confirmation_status,
)
from .schemas import (
    GateRecognitionEvent,
    VerificationResponse,
    OwnerConfirmationStatusResponse,
)
import logging

from redis.exceptions import RedisError    # type: ignore

from .idempotency import (
    acquire_event_lock,
    event_fingerprint,
    event_keys,
    get_cached_response,
    release_event_lock,
    save_cached_response,
)
from .movement_monitor import detect_suspicious_movement
from .scoring import calculate_risk, classify_risk

router = APIRouter()

MINIMUM_PLATE_CONFIDENCE = Decimal("0.8500")


@router.get("/health/")
async def health_check(request: Request):
    redis_status = "healthy"

    try:
        redis_client = request.app.state.redis
        await redis_client.ping()
    except Exception:
        redis_status = "unavailable"

    overall_status = (
        "healthy"
        if redis_status == "healthy"
        else "degraded"
    )

    return {
        "service": settings.SERVICE_NAME,
        "status": overall_status,
        "version": "1.0.0",
        "dependencies": {
            "django_api": "not_checked",
            "redis": redis_status,
        },
    }


def build_response(
    event: GateRecognitionEvent,
    decision: str,
    reason: str,
    lookup_result: dict | None = None,
) -> VerificationResponse:

    risk = calculate_risk(
        event,
        lookup_result or {},
    )

    return VerificationResponse(
        event_id=event.event_id,
        idempotency_key=event.idempotency_key,
        direction=event.direction,
        detected_registration=event.detected_registration,
        accepted=(decision == "ALLOW"),
        verification_status=decision,
        decision_reason=reason,
        confidence=event.confidence,
        risk_score=risk["risk_score"],
        risk_level=risk["risk_level"],
        risk_factors=risk["risk_factors"],
        lookup_result=lookup_result,
        message=(
            f"{event.direction.title()} verification result: "
            f"{decision}. {reason}"
        ),
    )


def apply_movement_signals(
    response: VerificationResponse,
    signals: list[dict],
) -> VerificationResponse:
    """
    Add temporal movement risk to the verification response.
    """

    if not signals:
        return response

    response.suspicious_activity = signals

    additional_points = sum(
        signal["points"]
        for signal in signals
    )

    if additional_points:
        response.risk_score = min(
            100,
            response.risk_score + additional_points,
        )

        response.risk_factors.extend([
            {
                "code": signal["code"],
                "points": signal["points"],
                "description": signal["description"],
            }
            for signal in signals
            if signal["points"] > 0
        ])

        response.risk_level = classify_risk(response.risk_score)   # type: ignore

    return response


def should_request_owner_confirmation(
    event: GateRecognitionEvent,
    response: VerificationResponse,
) -> bool:
    """
    Only request confirmation for a sufficiently reliable,
    registered, approved and active vehicle.

    Owner confirmation must never override mandatory
    access-control restrictions.
    """

    result = response.lookup_result or {}

    if event.confidence < float(MINIMUM_PLATE_CONFIDENCE):
        return False

    if response.verification_status != "REVIEW":
        return False

    if not result.get("estate_is_active", False):
        return False

    gate = result.get("gate_validation") or {}

    if not gate.get("exists", False):
        return False

    if not gate.get("is_valid", False):
        return False

    if not result.get("is_registered", False):
        return False

    if not result.get("is_approved", False):
        return False

    if not result.get("is_active", False):
        return False

    if event.direction == "ENTRY":
        # A duplicate entry with an existing session is
        # a candidate for owner/security review.
        return result.get("has_open_session", False)

    # EXIT requires a valid matching open session.
    # An unmatched exit must never be owner-approved.
    return False


async def request_owner_confirmation(
    event: GateRecognitionEvent,
    response: VerificationResponse,
) -> VerificationResponse:
    """
    Create a confirmation request in Django and attach
    its identifier and status to the verification response.
    """

    if not should_request_owner_confirmation(event, response):
        return response

    if response.risk_score < 25:
        return response

    result = response.lookup_result or {}
    vehicle = result.get("vehicle") or {}

    payload = {
        "event_id": str(event.event_id),
        "estate_id": str(event.estate_id),
        "gate_id": str(event.gate_id),
        "direction": event.direction,
        "detected_registration": event.detected_registration,
        "confidence": f"{event.confidence:.4f}",
        "risk_score": response.risk_score,
        "request_reason": response.decision_reason,
        "idempotency_key": str(event.idempotency_key),
        "evidence_object_key": event.evidence_object_key or "",
        "metadata": {
            "source": event.source,
            "verification_service": settings.SERVICE_NAME,
            "risk_level": response.risk_level,
            "vehicle_id": vehicle.get("id"),
        },
    }

    try:
        result = await create_owner_confirmation_request(payload)

    except DjangoServiceError as exc:
        logging.exception(
            "Failed to create owner confirmation for event %s",
            event.event_id,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not create the owner confirmation request.",
        ) from exc

    confirmation = result.get("confirmation")

    if not confirmation:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Django returned an invalid confirmation response.",
        )

    response.owner_confirmation_required = True
    response.owner_confirmation_id = confirmation["id"]
    response.owner_confirmation_status = confirmation["status"]

    response.message = (
        f"{response.message} "
        "Owner confirmation has been requested."
    )

    return response


def evaluate_entry(
    event: GateRecognitionEvent,
    lookup: dict,
) -> VerificationResponse:

    # Django returns the actual lookup data inside "result".
    result = lookup.get("result", lookup)

    # 1. Estate validation.
    if not result.get("estate_is_active", False):
        return build_response(
            event,
            "DENY",
            "The estate is inactive.",
            result,
        )

    # 2. Gate validation.
    gate = result.get("gate_validation")

    if not gate:
        return build_response(
            event,
            "REVIEW",
            "Gate validation information is missing.",
            result,
        )

    if not gate.get("exists", False):
        return build_response(
            event,
            "DENY",
            "The specified gate does not exist in this estate.",
            result,
        )

    if not gate.get("is_valid", False):
        return build_response(
            event,
            "DENY",
            gate.get(
                "reason",
                "The gate is not valid for entry.",
            ),
            result,
        )

    # 3. Plate confidence validation.
    confidence = Decimal(str(event.confidence))

    if confidence < MINIMUM_PLATE_CONFIDENCE:
        return build_response(
            event,
            "REVIEW",
            (
                f"Plate confidence {confidence:.4f} is below "
                f"the required threshold "
                f"{MINIMUM_PLATE_CONFIDENCE:.4f}."
            ),
            result,
        )

    # 4. Prevent duplicate entry while a session is open.
    if result.get("has_open_session", False):
        return build_response(
            event,
            "REVIEW",
            "This vehicle already has an open movement session.",
            result,
        )

    # 5. Registered vehicle validation.
    if result.get("is_registered", False):

        if not result.get("is_approved", False):
            return build_response(
                event,
                "DENY",
                "The registered vehicle has not been approved.",
                result,
            )

        if not result.get("is_active", False):
            return build_response(
                event,
                "DENY",
                "The registered vehicle is inactive.",
                result,
            )

        return build_response(
            event,
            "ALLOW",
            "Approved and active registered vehicle. No open session exists.",
            result,
        )

    # 6. Visitor vehicle validation.
    visitor_pass = result.get(
        "visitor_pass_validation",
        {},
    )

    if not visitor_pass.get("supplied", False):
        return build_response(
            event,
            "DENY",
            "Unregistered vehicle. No visitor pass was supplied.",
            result,
        )

    if not visitor_pass.get("exists", False):
        return build_response(
            event,
            "DENY",
            "The supplied visitor pass was not found.",
            result,
        )

    if not visitor_pass.get("registration_matches", False):
        return build_response(
            event,
            "DENY",
            "The visitor pass does not match this vehicle registration.",
            result,
        )

    if not visitor_pass.get("is_valid", False):
        return build_response(
            event,
            "DENY",
            visitor_pass.get(
                "reason",
                "The visitor pass is not valid.",
            ),
            result,
        )

    return build_response(
        event,
        "ALLOW",
        "Valid visitor pass and matching vehicle registration.",
        result,
    )

def evaluate_exit(
    event: GateRecognitionEvent,
    lookup: dict,
) -> VerificationResponse:

    result = lookup.get("result", lookup)

    # 1. Estate validation.
    if not result.get("estate_is_active", False):
        return build_response(
            event,
            "DENY",
            "The estate is inactive.",
            result,
        )

    # 2. Exit gate validation.
    gate = result.get("gate_validation")

    if not gate:
        return build_response(
            event,
            "REVIEW",
            "Gate validation information is missing.",
            result,
        )

    if not gate.get("exists", False):
        return build_response(
            event,
            "DENY",
            "The specified gate does not exist in this estate.",
            result,
        )

    if not gate.get("is_valid", False):
        return build_response(
            event,
            "DENY",
            gate.get(
                "reason",
                "The gate is not valid for exit.",
            ),
            result,
        )

    # 3. Plate confidence validation.
    confidence = Decimal(str(event.confidence))

    if confidence < MINIMUM_PLATE_CONFIDENCE:
        return build_response(
            event,
            "REVIEW",
            (
                f"Plate confidence {confidence:.4f} is below "
                f"the required threshold "
                f"{MINIMUM_PLATE_CONFIDENCE:.4f}."
            ),
            result,
        )

    # 4. A matching open movement session is required.
    if not result.get("has_open_session", False):
        return build_response(
            event,
            "REVIEW",
            "No matching open movement session was found for this vehicle.",
            result,
        )

    session = result.get("movement_session")

    if not session:
        return build_response(
            event,
            "REVIEW",
            "Open session information is incomplete.",
            result,
        )

    if session.get("status") != "OPEN":
        return build_response(
            event,
            "REVIEW",
            "The vehicle movement session is not open.",
            result,
        )

    if session.get("vehicle_registration") != result.get(
        "registration_number"
    ):
        return build_response(
            event,
            "REVIEW",
            "The movement session registration does not match.",
            result,
        )

    return build_response(
        event,
        "ALLOW",
        "Matching open movement session and valid exit gate.",
        result,
    )


@router.post(
    "/verification/events/",
    response_model=VerificationResponse,
    status_code=status.HTTP_200_OK,
)
async def receive_recognition_event(
    event: GateRecognitionEvent,
    request: Request,
):
    redis = request.app.state.redis

    fingerprint = event_fingerprint(event)
    result_key, lock_key = event_keys(event.idempotency_key)

    try:
        # 1. Return an existing result for an identical event.
        cached_response = await get_cached_response(
            redis,
            result_key,
            fingerprint,
        )

        if cached_response:
            return cached_response

        # 2. Prevent simultaneous processing.
        lock_token = await acquire_event_lock(
            redis,
            lock_key,
            fingerprint,
        )

    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is unavailable. Event verification cannot proceed safely.",
        ) from exc

    try:
        # 3. Recheck after acquiring the lock.
        cached_response = await get_cached_response(
            redis,
            result_key,
            fingerprint,
        )

        if cached_response:
            return cached_response

        # 4. Retrieve authoritative data from Django.
        try:
            lookup = await lookup_vehicle_session(
                estate_id=str(event.estate_id),
                registration_number=event.detected_registration,
                gate_id=str(event.gate_id),
                visitor_pass_code=event.visitor_pass_code,
                direction=event.direction,
            )

        except DjangoServiceError as exc:
            message = str(exc)

            if "not configured" in message.lower():
                error_status = status.HTTP_503_SERVICE_UNAVAILABLE
            elif "not found" in message.lower():
                error_status = status.HTTP_404_NOT_FOUND
            else:
                error_status = status.HTTP_502_BAD_GATEWAY

            raise HTTPException(
                status_code=error_status,
                detail=message,
            ) from exc

        # 5. Evaluate the event.
        if event.direction == "ENTRY":
            response = evaluate_entry(event, lookup)
        else:
            response = evaluate_exit(event, lookup)


        # Detect suspicious movement patterns using Redis history.
        redis_client = request.app.state.redis

        movement_signals = await detect_suspicious_movement(
            redis=redis_client,
            event=event,
            lookup=lookup,
        )

        # Attach movement intelligence to the verification result.
        response = apply_movement_signals(
            response=response,
            signals=movement_signals,
        )


        # 6. Request owner confirmation when eligible.
        response = await request_owner_confirmation(
            event,
            response,
        )

        # 7. Save the completed result in Redis.
        await save_cached_response(
            redis,
            result_key,
            fingerprint,
            response,
        )

        return response

    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis operation failed during event verification.",
        ) from exc

    finally:
        try:
            await release_event_lock(
                redis,
                lock_key,
                fingerprint,
                lock_token,
            )
        except RedisError:
            logging.exception("Failed to release verification event lock.")


@router.get("/verification/session-lookup/")
async def get_vehicle_session(
    estate_id: UUID,
    registration_number: str = Query(
        ...,
        min_length=2,
        max_length=30,
    ),
    gate_id: UUID | None = Query(default=None),
    visitor_pass_code: str | None = Query(default=None),
    direction: str = Query(
        default="ENTRY",
        pattern="^(ENTRY|EXIT)$",
    ),
):

    try:
        result = await lookup_vehicle_session(
            estate_id=str(estate_id),
            registration_number=registration_number,
            gate_id=str(gate_id) if gate_id else None,
            visitor_pass_code=visitor_pass_code,
            direction=direction,
        )

        return {
            "service": settings.SERVICE_NAME,
            "lookup_source": "django",
            "result": result,
        }

    except DjangoServiceError as exc:
        message = str(exc)

        if "not found" in message.lower():
            error_status = status.HTTP_404_NOT_FOUND
        elif "not configured" in message.lower():
            error_status = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            error_status = status.HTTP_502_BAD_GATEWAY

        raise HTTPException(
            status_code=error_status,
            detail=message,
        ) from exc


@router.get(
    "/verification/owner-confirmations/{event_id}/",
    response_model=OwnerConfirmationStatusResponse,
)
async def retrieve_owner_confirmation_status(
    event_id: UUID,
):
    """
    Retrieve the latest owner-confirmation status from Django.

    Django remains the authoritative source for confirmation
    status and response timestamps.
    """

    try:
        result = await get_owner_confirmation_status(
            str(event_id)
        )

        return OwnerConfirmationStatusResponse.model_validate(
            result
        )

    except DjangoServiceError as exc:
        message = str(exc)

        if "not found" in message.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=message,
            ) from exc

        logging.exception(
            "Could not retrieve owner confirmation for event %s",
            event_id,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not retrieve owner confirmation status.",
        ) from exc



@router.get(
    "/verification/events/{event_id}/owner-status/",
    response_model=OwnerConfirmationStatusResponse,
)
async def get_event_owner_status(
    event_id: UUID,
):
    """
    Retrieve owner confirmation status for a recognition event.

    This endpoint is intended for monitoring the outcome of
    owner review after the initial verification decision.
    """

    try:
        result = await get_owner_confirmation_status(
            str(event_id)
        )

        return OwnerConfirmationStatusResponse.model_validate(
            result
        )

    except DjangoServiceError as exc:
        message = str(exc)

        if "not found" in message.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=message,
            ) from exc

        logging.exception(
            "Owner status lookup failed for event %s",
            event_id,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve owner confirmation status.",
        ) from exc

