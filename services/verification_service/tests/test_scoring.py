from datetime import datetime, timezone
from uuid import uuid4

from services.verification_service.app.schemas import GateRecognitionEvent
from services.verification_service.app.scoring import calculate_risk


def make_event(direction="ENTRY", confidence=0.95):
    return GateRecognitionEvent(
        event_id=uuid4(),
        schema_version="1.0",
        event_type=(
            "VEHICLE_ENTRY"
            if direction == "ENTRY"
            else "VEHICLE_EXIT"
        ),
        occurred_at=datetime.now(timezone.utc),
        estate_id=uuid4(),
        gate_id=uuid4(),
        direction=direction,
        detected_registration="KDA123A",
        confidence=confidence,
        source="ANPR",
        idempotency_key=uuid4(),
    )


def valid_lookup():
    return {
        "estate_is_active": True,
        "is_registered": True,
        "is_approved": True,
        "is_active": True,
        "has_open_session": False,
        "gate_validation": {
            "exists": True,
            "is_valid": True,
        },
        "visitor_pass_validation": {
            "is_valid": False,
        },
    }


def test_approved_registered_vehicle_has_low_risk():
    result = calculate_risk(
        make_event(),
        valid_lookup(),
    )

    assert result["risk_score"] == 0
    assert result["risk_level"] == "LOW"


def test_low_confidence_plate_adds_risk():
    result = calculate_risk(
        make_event(confidence=0.60),
        valid_lookup(),
    )

    assert result["risk_score"] == 45
    assert result["risk_level"] == "MEDIUM"


def test_valid_visitor_pass_adds_ten_points():
    lookup = valid_lookup()
    lookup["is_registered"] = False
    lookup["visitor_pass_validation"] = {
        "is_valid": True,
    }

    result = calculate_risk(
        make_event(),
        lookup,
    )

    assert result["risk_score"] == 10
    assert result["risk_level"] == "LOW"


def test_exit_without_open_session_is_high_risk():
    result = calculate_risk(
        make_event(direction="EXIT"),
        valid_lookup(),
    )

    assert result["risk_score"] == 50
    assert result["risk_level"] == "HIGH"


def test_risk_score_is_capped_at_100():
    lookup = {
        "estate_is_active": False,
        "is_registered": True,
        "is_approved": False,
        "is_active": False,
        "has_open_session": True,
        "gate_validation": {
            "exists": False,
            "is_valid": False,
        },
    }

    result = calculate_risk(
        make_event(confidence=0.50),
        lookup,
    )

    assert result["risk_score"] == 100
    assert result["risk_level"] == "CRITICAL"
