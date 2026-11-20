import json
import logging
import os
import signal
import sys
import time

from datetime import datetime, timezone

import requests

from confluent_kafka import Consumer, KafkaError # type: ignore
from dotenv import load_dotenv
from pydantic import ValidationError             # type: ignore

from services.shared.event_contract import GateEvent

from services.event_consumer.processor import EventProcessor
from services.event_consumer.dedupe import EventLedger
from services.event_consumer.django_client import DjangoGateClient

from services.event_consumer.reliability import (
    EventPublisher,
    RETRY_TOPIC,
    DLQ_TOPIC,
    MAX_RETRIES,
    create_retry_envelope,
    create_dlq_envelope,
    is_transient_error,
)


load_dotenv(".env.phase3")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("gate-retry-consumer")

BOOTSTRAP = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "localhost:9092",
)

GROUP = os.getenv(
    "KAFKA_RETRY_CONSUMER_GROUP",
    "estate-gate-retry-v1",
)

LEDGER_PATH = os.getenv(
    "EVENT_LEDGER_PATH",
    "services/event_consumer/processed_events.db",
)

running = True


def stop_consumer(signum, frame):
    global running
    running = False
    logger.info("Retry worker shutdown requested")


signal.signal(signal.SIGINT, stop_consumer)
signal.signal(signal.SIGTERM, stop_consumer)


class GateRetryConsumer:

    def __init__(self):

        self.consumer = Consumer({
            "bootstrap.servers": BOOTSTRAP,
            "group.id": GROUP,
            "client.id": "estate-gate-retry-worker",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
            "session.timeout.ms": 45000,
            "max.poll.interval.ms": 300000,
        })

        self.ledger = EventLedger(LEDGER_PATH)
        self.django = DjangoGateClient()

        # Use the same processing pipeline as the main consumer.
        self.processor = EventProcessor(
            django_client=self.django,
        )

        self.publisher = EventPublisher(BOOTSTRAP)

    def commit(self, message):

        self.consumer.commit(
            message=message,
            asynchronous=False,
        )

        logger.info(
            "Retry offset committed: partition=%s offset=%s",
            message.partition(),
            message.offset(),
        )

    def send_to_dlq(
        self,
        raw_payload,
        event_id,
        error,
        source_topic,
        attempts,
    ):

        envelope = create_dlq_envelope(
            raw_payload=raw_payload,
            event_id=event_id,
            error=error,
            source_topic=source_topic,
            attempts=attempts,
        )

        self.publisher.publish(
            topic=DLQ_TOPIC,
            key=event_id or envelope["dlq_id"],
            payload=envelope,
        )

        logger.error(
            "Retry exhausted or permanent failure. "
            "Sent to DLQ: %s",
            event_id,
        )

    def process_message(self, message):

        raw_retry = message.value().decode("utf-8")

        try:
            envelope = json.loads(raw_retry)

            if not isinstance(envelope, dict):
                raise ValueError("Retry envelope must be an object")

            raw_event = envelope["original_payload"]
            event_id = envelope["event_id"]
            attempt = int(envelope["attempt"])
            retry_at = float(envelope["retry_at"])

            if not isinstance(raw_event, str):
                raise ValueError(
                    "Original payload must be a JSON string"
                )

            if not event_id or attempt < 1 or retry_at <= 0:
                raise ValueError(
                    "Invalid retry envelope metadata"
                )

        except (ValueError, TypeError, KeyError) as exc:

            self.send_to_dlq(
                raw_payload=raw_retry,
                event_id=None,
                error=exc,
                source_topic=RETRY_TOPIC,
                attempts=0,
            )

            self.commit(message)
            return

        retry_at = float(envelope["retry_at"])

        remaining = max(
            0,
            retry_at - datetime.now(timezone.utc).timestamp(),
        )

        if remaining > 0:

            logger.info(
                "Retry %s scheduled in %.1f seconds",
                attempt,
                remaining,
            )

            # Development implementation of delayed retries.
            # Maximum configured delay is 60 seconds.
            time.sleep(remaining)

        try:

            event = GateEvent.model_validate_json(raw_event)

            if str(event.event_id) != str(event_id):
                raise ValueError(
                    "Retry event ID does not match original event"
                )

        except (ValidationError, ValueError) as exc:

            self.send_to_dlq(
                raw_payload=raw_event,
                event_id=event_id,
                error=exc,
                source_topic=envelope.get(
                    "source_topic",
                    RETRY_TOPIC,
                ),
                attempts=attempt,
            )

            self.commit(message)
            return

        if self.ledger.is_processed(event.event_id):

            logger.info(
                "Retry skipped because event is already processed: %s",
                event_id,
            )

            self.commit(message)
            return

        try:

            self.processor.process_event(event)

            self.ledger.mark_processed(
                event.event_id,
                event.idempotency_key,
            )

            logger.info(
                "Retry succeeded: event=%s attempt=%s",
                event_id,
                attempt,
            )

            self.commit(message)

        except requests.RequestException as exc:

            if not is_transient_error(exc):

                self.send_to_dlq(
                    raw_payload=raw_event,
                    event_id=event_id,
                    error=exc,
                    source_topic=envelope.get(
                        "source_topic",
                        RETRY_TOPIC,
                    ),
                    attempts=attempt,
                )

                self.commit(message)
                return

            if attempt >= MAX_RETRIES:

                self.send_to_dlq(
                    raw_payload=raw_event,
                    event_id=event_id,
                    error=exc,
                    source_topic=envelope.get(
                        "source_topic",
                        RETRY_TOPIC,
                    ),
                    attempts=attempt,
                )

                self.commit(message)
                return

            next_attempt = attempt + 1

            next_envelope = create_retry_envelope(
                raw_payload=raw_event,
                event_id=event_id,
                attempt=next_attempt,
                error=exc,
                source_topic=envelope.get(
                    "source_topic",
                    RETRY_TOPIC,
                ),
            )

            self.publisher.publish(
                topic=RETRY_TOPIC,
                key=event_id,
                payload=next_envelope,
            )

            logger.warning(
                "Retry scheduled: event=%s next_attempt=%s",
                event_id,
                next_attempt,
            )

            self.commit(message)

        except Exception:

            # Unexpected errors are not silently discarded.
            # Do not commit the retry message.
            logger.exception(
                "Unexpected retry worker failure: %s",
                event_id,
            )

            raise

    def run(self):

        self.consumer.subscribe([RETRY_TOPIC])

        logger.info(
            "Retry consumer subscribed to %s",
            RETRY_TOPIC,
        )

        try:

            while running:

                message = self.consumer.poll(1.0)

                if message is None:
                    continue

                if message.error():

                    if message.error().code() == KafkaError._PARTITION_EOF:
                        continue

                    raise RuntimeError(str(message.error()))

                try:
                    self.process_message(message)

                except Exception:
                    logger.exception(
                        "Retry message processing failed. "
                        "Offset remains uncommitted."
                    )
                    raise

        finally:
            self.close()

    def close(self):

        self.consumer.close()
        self.publisher.close()
        self.ledger.close()
        self.django.close()


if __name__ == "__main__":

    try:
        GateRetryConsumer().run()

    except Exception:
        logger.exception("Retry worker terminated")
        sys.exit(1)
