import json
import logging
import math
import os
import requests

from datetime import datetime, timezone
from uuid import uuid4
from confluent_kafka import Producer # type: ignore
from dotenv import load_dotenv

load_dotenv(".env.phase3")

logger = logging.getLogger("event-reliability")

RETRY_TOPIC = "gate.access.retry.v1"
DLQ_TOPIC = "gate.access.dlq.v1"

MAX_RETRIES = int(os.getenv("KAFKA_MAX_RETRIES", "5"))

BASE_DELAY_SECONDS = int(
    os.getenv("KAFKA_RETRY_BASE_DELAY", "2")
)

MAX_DELAY_SECONDS = int(
    os.getenv("KAFKA_RETRY_MAX_DELAY", "60")
)


class EventPublisher:

    def __init__(self, bootstrap_servers):

        self.producer = Producer({
            "bootstrap.servers": bootstrap_servers,
            "client.id": "estate-event-reliability",
            "acks": "all",
            "enable.idempotence": True,
            "retries": 10,
        })

    def publish(self, topic, key, payload):

        delivery_errors = []

        def callback(error, message):
            if error is not None:
                delivery_errors.append(str(error))

        self.producer.produce(
            topic=topic,
            key=str(key),
            value=json.dumps(payload).encode("utf-8"),
            callback=callback,
        )

        remaining = self.producer.flush(15)

        if remaining > 0:
            raise RuntimeError(
                f"Kafka delivery timed out: {remaining} messages remain"
            )

        if delivery_errors:
            raise RuntimeError(
                f"Kafka delivery failed: {delivery_errors}"
            )

        logger.info(
            "Published message to %s",
            topic,
        )

    def close(self):
        remaining = self.producer.flush(15)

        if remaining > 0:
            logger.error(
                "%s Kafka messages remain undelivered",
                remaining,
            )


def calculate_retry_delay(attempt):

    delay = BASE_DELAY_SECONDS * math.pow(2, attempt - 1)

    return min(delay, MAX_DELAY_SECONDS)


def create_retry_envelope(
    raw_payload,
    event_id,
    attempt,
    error,
    source_topic,
):

    delay = calculate_retry_delay(attempt)

    retry_at = (
        datetime.now(timezone.utc).timestamp() + delay
    )

    return {
        "retry_id": str(uuid4()),
        "event_id": str(event_id),
        "attempt": attempt,
        "max_attempts": MAX_RETRIES,
        "retry_at": retry_at,
        "last_error": str(error)[:2000],
        "source_topic": source_topic,
        "original_payload": raw_payload,
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


def create_dlq_envelope(
    raw_payload,
    event_id,
    error,
    source_topic,
    attempts=0,
):

    return {
        "dlq_id": str(uuid4()),
        "event_id": str(event_id) if event_id else None,
        "source_topic": source_topic,
        "attempts": attempts,
        "error": str(error)[:4000],
        "original_payload": raw_payload,
        "failed_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": "PENDING_INVESTIGATION",
    }


def is_transient_error(exc):

    if isinstance(
        exc,
        (
            requests.ConnectionError,
            requests.Timeout,
        ),
    ):
        return True

    if isinstance(exc, requests.HTTPError):

        response = exc.response

        if response is None:
            return True

        status = response.status_code

        return (
            status in (408, 425, 429)
            or 500 <= status <= 599
        )

    return False
