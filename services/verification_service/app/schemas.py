from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (          # type: ignore
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class GateRecognitionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    schema_version: Literal["1.0"]
    event_type: Literal["VEHICLE_ENTRY", "VEHICLE_EXIT"]
    occurred_at: datetime

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

    source: Literal["SIMULATOR", "ANPR", "MANUAL"]

    idempotency_key: UUID

    visitor_pass_code: str | None = None
    evidence_object_key: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_event_direction(self):
        expected_event_type = (
            "VEHICLE_ENTRY"
            if self.direction == "ENTRY"
            else "VEHICLE_EXIT"
        )

        if self.event_type != expected_event_type:
            raise ValueError(
                "event_type does not match direction."
            )

        return self



class VerificationResponse(BaseModel):
    event_id: UUID
    idempotency_key: UUID
    direction: Literal["ENTRY", "EXIT"]
    detected_registration: str

    accepted: bool

    verification_status: Literal[
        "PENDING",
        "ALLOW",
        "DENY",
        "REVIEW",
    ]

    decision_reason: str
    confidence: float

    risk_score: int = Field(default=0, ge=0, le=100)

    risk_level: Literal[
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
    ] = "LOW"

    risk_factors: list[dict[str, Any]] = Field(
        default_factory=list
    )

    suspicious_activity: list[dict[str, Any]] = Field(
        default_factory=list
    )

    lookup_result: dict[str, Any] | None = None

    owner_confirmation_required: bool = False

    owner_confirmation_id: UUID | None = None

    owner_confirmation_status: Literal[
        "PENDING",
        "CONFIRMED",
        "REJECTED",
        "EXPIRED",
    ] | None = None

    message: str


class OwnerConfirmationStatusResponse(BaseModel):
    id: UUID
    event_id: UUID

    status: Literal[
        "PENDING",
        "CONFIRMED",
        "REJECTED",
        "EXPIRED",
    ]

    expires_at: datetime
    responded_at: datetime | None = None
    response_note: str = ""
