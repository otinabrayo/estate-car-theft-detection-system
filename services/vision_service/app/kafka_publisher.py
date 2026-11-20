import logging
import json

from datetime import datetime, timezone
from functools import lru_cache
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from typing import Literal

from kafka import KafkaProducer                     # type: ignore
from pydantic import BaseModel, ConfigDict, Field   # type: ignore

from .config import (
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_ENTRY_TOPIC,
    KAFKA_EXIT_TOPIC,
)

logger = logging.getLogger(__name__)


def _serialize_kafka_key(key: object) -> bytes:
    if isinstance(key, str):
        return key.encode("utf-8")
    if isinstance(key, bytes):
        return key
    raise TypeError("Kafka key must be a string or bytes")


class GateRecognitionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    schema_version: Literal["1.0"] = "1.0"

    event_type: Literal[
        "VEHICLE_ENTRY",
        "VEHICLE_EXIT",
    ]

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

    source: Literal[
        "SIMULATOR",
        "ANPR",
        "MANUAL",
    ] = "ANPR"

    idempotency_key: UUID

    visitor_pass_code: str | None = None
    evidence_object_key: str | None = None

    metadata: dict = Field(default_factory=dict)


@lru_cache(maxsize=1)
def get_kafka_producer():

    logger.info(
        "Connecting vision service to Kafka: %s",
        KAFKA_BOOTSTRAP_SERVERS,
    )

    return KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS.split(","),
        key_serializer=_serialize_kafka_key,
        value_serializer=lambda value: json.dumps(
            value
        ).encode("utf-8"),
        acks="all",
        retries=5,
        retry_backoff_ms=500,
        max_in_flight_requests_per_connection=1,
        request_timeout_ms=30000,
        max_block_ms=15000,
        compression_type="gzip",
    )


def publish_recognition_event(
    *,
    video_id: UUID,
    estate_id: UUID,
    gate_id: UUID,
    direction: Literal["ENTRY", "EXIT"],
    registration: str,
    confidence: float,
    evidence_object_key: str,
    metadata: dict,
):

    if direction not in ("ENTRY", "EXIT"):
        raise ValueError("Unsupported gate direction.")

    # One event per plate, video, gate and direction.
    # Reprocessing the same video produces the same idempotency key.
    idempotency_key = uuid5(
        NAMESPACE_URL,
        (
            f"estate-anpr:{video_id}:"
            f"{estate_id}:{gate_id}:"
            f"{direction}:{registration}"
        ),
    )

    event_type = (
        "VEHICLE_ENTRY"
        if direction == "ENTRY"
        else "VEHICLE_EXIT"
    )

    topic = (
        KAFKA_ENTRY_TOPIC
        if direction == "ENTRY"
        else KAFKA_EXIT_TOPIC
    )

    event = GateRecognitionEvent(
        event_id=uuid4(),
        schema_version="1.0",
        event_type=event_type,
        occurred_at=datetime.now(timezone.utc),
        estate_id=estate_id,
        gate_id=gate_id,
        direction=direction,
        detected_registration=registration,
        confidence=confidence,
        source="ANPR",
        idempotency_key=idempotency_key,
        visitor_pass_code=None,
        evidence_object_key=evidence_object_key,
        metadata=metadata,
    )

    payload = event.model_dump(mode="json")

    producer = get_kafka_producer()

    try:
        future = producer.send(
            topic,
            key=str(idempotency_key),
            value=payload,
        )

        record_metadata = future.get(timeout=30)

        logger.info(
            "Recognition event published: topic=%s partition=%s offset=%s",
            record_metadata.topic,
            record_metadata.partition,
            record_metadata.offset,
        )

        return {
            "event_id": str(event.event_id),
            "idempotency_key": str(idempotency_key),
            "topic": record_metadata.topic,
            "partition": record_metadata.partition,
            "offset": record_metadata.offset,
            "registration": registration,
            "status": "PUBLISHED",
        }

    except Exception:
        logger.exception(
            "Failed to publish recognition event for %s",
            registration,
        )
        raise
