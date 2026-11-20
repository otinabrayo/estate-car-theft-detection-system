from typing import Any

from .schemas import GateRecognitionEvent


RISK_LEVELS = {
    "LOW": (0, 24),
    "MEDIUM": (25, 49),
    "HIGH": (50, 74),
    "CRITICAL": (75, 100),
}


def classify_risk(score: int) -> str:
    for level, (minimum, maximum) in RISK_LEVELS.items():
        if minimum <= score <= maximum:
            return level

    return "CRITICAL"


def calculate_risk(
    event: GateRecognitionEvent,
    lookup: dict[str, Any],
) -> dict[str, Any]:
    """
    Calculate a transparent risk assessment.

    This function does not make access-control decisions.
    Django remains the authoritative source for access decisions.
    """

    raw_score = 0
    factors: list[dict[str, Any]] = []

    def add_factor(
        code: str,
        points: int,
        description: str,
    ) -> None:
        nonlocal raw_score

        raw_score += points

        factors.append({
            "code": code,
            "points": points,
            "description": description,
        })

    # 1. Plate recognition confidence.
    if event.confidence < 0.85:
        add_factor(
            "LOW_PLATE_CONFIDENCE",
            30,
            "Plate recognition confidence is below 0.85.",
        )

    if event.confidence < 0.65:
        add_factor(
            "VERY_LOW_PLATE_CONFIDENCE",
            15,
            "Plate recognition confidence is below 0.65.",
        )

    # 2. Estate status.
    if not lookup.get("estate_is_active", False):
        add_factor(
            "INACTIVE_ESTATE",
            100,
            "The estate is inactive or unavailable.",
        )

    # 3. Gate validation.
    gate = lookup.get("gate_validation") or {}

    if not gate.get("exists", False) or not gate.get("is_valid", False):
        add_factor(
            "INVALID_GATE",
            60,
            "The gate is missing, inactive, or invalid for this direction.",
        )

    # 4. Registered vehicle status.
    is_registered = lookup.get("is_registered", False)

    if is_registered:
        is_approved = lookup.get("is_approved", False)
        is_active = lookup.get("is_active", False)

        if not is_approved or not is_active:
            add_factor(
                "UNAPPROVED_OR_INACTIVE_VEHICLE",
                70,
                "The registered vehicle is not approved or active.",
            )

    # 5. Visitor pass validation for unregistered vehicles.
    else:
        visitor_pass = lookup.get("visitor_pass_validation") or {}

        if visitor_pass.get("is_valid", False):
            add_factor(
                "VISITOR_VEHICLE",
                10,
                "The unregistered vehicle is using a valid visitor pass.",
            )
        else:
            add_factor(
                "INVALID_OR_MISSING_VISITOR_PASS",
                60,
                "The unregistered vehicle has no valid visitor pass.",
            )

    # 6. Movement-session checks.
    has_open_session = lookup.get("has_open_session", False)

    if event.direction == "ENTRY" and has_open_session:
        add_factor(
            "ENTRY_WITH_OPEN_SESSION",
            40,
            "The vehicle already has an open movement session.",
        )

    if event.direction == "EXIT" and not has_open_session:
        add_factor(
            "EXIT_WITHOUT_OPEN_SESSION",
            50,
            "No open movement session exists for this vehicle.",
        )

    # Cap the final score at 100.
    final_score = min(raw_score, 100)

    return {
        "risk_score": final_score,
        "risk_level": classify_risk(final_score),
        "risk_factors": factors,
    }
