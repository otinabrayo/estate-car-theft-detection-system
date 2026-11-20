import hashlib
import json
import re
from datetime import timezone
from typing import Any

from .schemas import GateRecognitionEvent


MOVEMENT_WINDOW_SECONDS = 120
RAPID_DIRECTION_CHANGE_SECONDS = 90
REPEATED_RECOGNITION_SECONDS = 20
MOVEMENT_HISTORY_TTL_SECONDS = 300


RECORD_MOVEMENT_SCRIPT = """
local previous = redis.call(
    'ZRANGEBYSCORE',
    KEYS[1],
    ARGV[1],
    ARGV[2]
)

redis.call(
    'ZADD',
    KEYS[1],
    ARGV[3],
    ARGV[4]
)

redis.call(
    'ZREMRANGEBYSCORE',
    KEYS[1],
    '-inf',
    ARGV[5]
)

redis.call(
    'ZREMRANGEBYRANK',
    KEYS[1],
    0,
    -51
)

redis.call(
    'EXPIRE',
    KEYS[1],
    ARGV[6]
)

return previous
"""


def normalize_registration(value: str) -> str:
    return re.sub(r"[\s-]+", "", value).upper()


def get_movement_history_key(
    estate_id: str,
    registration: str,
) -> str:
    """
    Hash the vehicle identity so registration numbers
    are not exposed directly in Redis key names.
    """

    identity = (
        f"{estate_id}:"
        f"{normalize_registration(registration)}"
    )

    digest = hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()

    return f"estate:movement-history:{digest}"


def build_movement_signals(
    event: GateRecognitionEvent,
    lookup: dict[str, Any],
    previous_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Detect suspicious patterns using current lookup data
    and recent movement observations.
    """

    signals = []

    def add_signal(
        code: str,
        severity: str,
        points: int,
        description: str,
    ):
        if not any(
            item["code"] == code
            for item in signals
        ):
            signals.append({
                "code": code,
                "severity": severity,
                "points": points,
                "description": description,
            })

    # Rule 1: Duplicate entry.
    if (
        event.direction == "ENTRY"
        and lookup.get("has_open_session", False)
    ):
        add_signal(
            code="DUPLICATE_ENTRY_WITH_OPEN_SESSION",
            severity="HIGH",
            points=0,
            description=(
                "Vehicle attempted entry while an open "
                "movement session already exists."
            ),
        )

    # Rule 2: Exit without an open session.
    if (
        event.direction == "EXIT"
        and lookup.get("has_open_session") is False   
    ):
        add_signal(
            code="EXIT_WITHOUT_OPEN_SESSION",
            severity="HIGH",
            points=0,
            description=(
                "Vehicle was detected exiting without "
                "an existing open movement session."
            ),
        )

    current_time = event.occurred_at

    if current_time.tzinfo is None:
        current_time = current_time.replace(
            tzinfo=timezone.utc
        )

    current_timestamp = current_time.timestamp()

    for previous in previous_events:
        previous_direction = previous.get("direction")
        previous_gate = previous.get("gate_id")

        previous_time = previous.get("timestamp")

        if previous_time is None:
            continue

        time_difference = abs(
            current_timestamp - float(previous_time)
        )

        # Rule 3: Rapid direction change.
        if (
            previous_direction != event.direction
            and time_difference
            <= RAPID_DIRECTION_CHANGE_SECONDS
        ):
            add_signal(
                code="RAPID_DIRECTION_CHANGE",
                severity="HIGH",
                points=20,
                description=(
                    "The same vehicle registration was "
                    "detected entering and exiting within "
                    "a short time window."
                ),
            )

        # Rule 4: Same registration at different gates.
        if (
            previous_gate
            and previous_gate != str(event.gate_id)
            and time_difference <= MOVEMENT_WINDOW_SECONDS
        ):
            add_signal(
                code="MULTIPLE_GATES_SHORT_WINDOW",
                severity="HIGH",
                points=30,
                description=(
                    "The same vehicle registration was "
                    "detected at different gates within "
                    "a short time window."
                ),
            )

        # Rule 5: Repeated recognition at the same gate.
        if (
            previous_direction == event.direction
            and previous_gate == str(event.gate_id)
            and time_difference <= REPEATED_RECOGNITION_SECONDS
        ):
            add_signal(
                code="REPEATED_RECOGNITION",
                severity="LOW",
                points=10,
                description=(
                    "The same vehicle registration was "
                    "recognized repeatedly at the same gate "
                    "within a short time window."
                ),
            )

    return signals


async def detect_suspicious_movement(
    redis,
    event: GateRecognitionEvent,
    lookup: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Atomically retrieve recent vehicle observations and
    record the current event in Redis.
    """

    event_time = event.occurred_at

    if event_time.tzinfo is None:
        event_time = event_time.replace(
            tzinfo=timezone.utc
        )

    timestamp = event_time.timestamp()

    key = get_movement_history_key(
        str(event.estate_id),
        event.detected_registration,
    )

    current_record = {
        "event_id": str(event.event_id),
        "direction": event.direction,
        "gate_id": str(event.gate_id),
        "timestamp": timestamp,
    }

    previous_records = await redis.eval(
        RECORD_MOVEMENT_SCRIPT,
        1,
        key,
        timestamp - MOVEMENT_WINDOW_SECONDS,
        timestamp + MOVEMENT_WINDOW_SECONDS,
        timestamp,
        json.dumps(current_record),
        timestamp - MOVEMENT_WINDOW_SECONDS,
        MOVEMENT_HISTORY_TTL_SECONDS,
    )

    previous_events = [
        json.loads(record)
        for record in previous_records
    ]

    return build_movement_signals(
        event=event,
        lookup=lookup,
        previous_events=previous_events,
    )
