from uuid import uuid4

from services.verification_service.app.routes import (
    apply_movement_signals,
)
from services.verification_service.app.schemas import (
    VerificationResponse,
)


def make_response():
    return VerificationResponse(
        event_id=uuid4(),
        idempotency_key=uuid4(),
        direction="ENTRY",
        detected_registration="KCP697S",
        accepted=False,
        verification_status="REVIEW",
        decision_reason="Movement requires review.",
        message="Movement requires review.",
        confidence=0.95,
        risk_score=10,
        risk_level="LOW",
    )


def test_movement_signals_increase_risk_score():
    response = make_response()

    signals = [
        {
            "code": "RAPID_DIRECTION_CHANGE",
            "severity": "HIGH",
            "points": 20,
            "description": "Rapid direction change.",
        }
    ]

    result = apply_movement_signals(
        response,
        signals,
    )

    assert result.risk_score == 30
    assert result.risk_level == "MEDIUM"
    assert len(result.suspicious_activity) == 1


def test_movement_risk_score_is_capped_at_100():
    response = make_response()
    response.risk_score = 90

    signals = [
        {
            "code": "MULTIPLE_GATES_SHORT_WINDOW",
            "severity": "HIGH",
            "points": 30,
            "description": "Multiple gates.",
        }
    ]

    result = apply_movement_signals(
        response,
        signals,
    )

    assert result.risk_score == 100
    assert result.risk_level == "CRITICAL"


def test_no_signals_do_not_change_risk_score():
    response = make_response()

    result = apply_movement_signals(
        response,
        [],
    )

    assert result.risk_score == 10
    assert result.suspicious_activity == []
