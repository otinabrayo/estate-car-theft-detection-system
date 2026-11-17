from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import (    # type: ignore
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class GateEvent(BaseModel):

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    event_id: UUID = Field(default_factory=uuid4)

    schema_version: Literal["1.0"] = "1.0"

    event_type: Literal[
        "VEHICLE_ENTRY",
        "VEHICLE_EXIT",
    ]

    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    estate_id: UUID
    gate_id: UUID

    direction: Literal["ENTRY", "EXIT"]

    detected_registration: str = Field(
        min_length=2,
        max_length=20,
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    source: Literal[
        "SIMULATOR",
        "ANPR",
        "MANUAL",
    ] = "SIMULATOR"

    idempotency_key: UUID = Field(
        default_factory=uuid4
    )

    visitor_pass_code: str | None = None

    evidence_object_key: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_direction(self):

        expected_type = {
            "ENTRY": "VEHICLE_ENTRY",
            "EXIT": "VEHICLE_EXIT",
        }

        if expected_type[self.direction] != self.event_type:
            raise ValueError(
                "Event type does not match direction"
            )

        return self
