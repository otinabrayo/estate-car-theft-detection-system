from datetime import datetime, timedelta, timezone
from uuid import uuid4

from services.verification_service.app.movement_monitor import (
    build_movement_signals,
    get_movement_history_key,
)
from services.verification_service.app.schemas import (
    GateRecognitionEvent,
)


ESTATE_ID = uuid4()
GATE_A = uuid4()
GATE_B = uuid4()


def make_event(
    direction="ENTRY",
    gate_id=GATE_A,
    occurred_at=None,
):
    return GateRecognitionEvent(
        event_id=uuid4(),
        schema_version="1.0",
        event_type=(
            "VEHICLE_ENTRY"
            if direction == "ENTRY"
            else "VEHICLE_EXIT"
        ),
        occurred_at=(
            occurred_at
            or datetime.now(timezone.utc)
        ),
        estate_id=ESTATE_ID,
        gate_id=gate_id,
        direction=direction,
        detected_registration="KCP 697S",
        confidence=0.95,
        source="ANPR",
        idempotency_key=uuid4(),
    )


def test_detects_duplicate_entry_with_open_session():
    event = make_event("ENTRY")

    signals = build_movement_signals(
        event,
        {"has_open_session": True},
        [],
    )

    assert any(
        signal["code"]
        == "DUPLICATE_ENTRY_WITH_OPEN_SESSION"
        for signal in signals
    )


def test_detects_exit_without_open_session():
    event = make_event("EXIT")

    signals = build_movement_signals(
        event,
        {"has_open_session": False},
        [],
    )

    assert any(
        signal["code"] == "EXIT_WITHOUT_OPEN_SESSION"
        for signal in signals
    )


def test_detects_rapid_direction_change():
    now = datetime.now(timezone.utc)

    event = make_event(
        direction="EXIT",
        occurred_at=now,
    )

    previous = [{
        "event_id": str(uuid4()),
        "direction": "ENTRY",
        "gate_id": str(GATE_A),
        "timestamp": (now - timedelta(seconds=30)).timestamp(),
    }]

    signals = build_movement_signals(
        event,
        {},
        previous,
    )

    assert any(
        signal["code"] == "RAPID_DIRECTION_CHANGE"
        for signal in signals
    )


def test_detects_same_vehicle_at_different_gates():
    now = datetime.now(timezone.utc)

    event = make_event(
        direction="ENTRY",
        gate_id=GATE_B,
        occurred_at=now,
    )

    previous = [{
        "event_id": str(uuid4()),
        "direction": "ENTRY",
        "gate_id": str(GATE_A),
        "timestamp": (now - timedelta(seconds=45)).timestamp(),
    }]

    signals = build_movement_signals(
        event,
        {},
        previous,
    )

    assert any(
        signal["code"] == "MULTIPLE_GATES_SHORT_WINDOW"
        for signal in signals
    )


def test_detects_repeated_recognition():
    now = datetime.now(timezone.utc)

    event = make_event(
        direction="ENTRY",
        gate_id=GATE_A,
        occurred_at=now,
    )

    previous = [{
        "event_id": str(uuid4()),
        "direction": "ENTRY",
        "gate_id": str(GATE_A),
        "timestamp": (now - timedelta(seconds=10)).timestamp(),
    }]

    signals = build_movement_signals(
        event,
        {},
        previous,
    )

    assert any(
        signal["code"] == "REPEATED_RECOGNITION"
        for signal in signals
    )


def test_does_not_flag_old_movement():
    now = datetime.now(timezone.utc)

    event = make_event(
        direction="EXIT",
        occurred_at=now,
    )

    previous = [{
        "event_id": str(uuid4()),
        "direction": "ENTRY",
        "gate_id": str(GATE_A),
        "timestamp": (now - timedelta(minutes=10)).timestamp(),
    }]

    signals = build_movement_signals(
        event,
        {},
        previous,
    )

    assert signals == []


def test_movement_history_key_does_not_expose_registration():
    key = get_movement_history_key(
        str(ESTATE_ID),
        "KCP 697S",
    )

    assert "KCP" not in key
    assert "697S" not in key
    assert key.startswith("estate:movement-history:")
