import json
import logging
import os
import signal
import sys
import requests

from confluent_kafka import Consumer, KafkaError # type: ignore
from dotenv import load_dotenv
from pydantic import ValidationError             # type: ignore

from services.shared.event_contract import GateEvent

from services.event_consumer.dedupe import EventLedger
from services.event_consumer.processor import EventProcessor
from services.event_consumer.django_client import DjangoGateClient
from services.event_consumer.reliability import (
    EventPublisher,
    RETRY_TOPIC,
    create_retry_envelope,
    create_dlq_envelope,
    is_transient_error,
    MAX_RETRIES,
)

load_dotenv(".env.phase3")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("gate-consumer")

BOOTSTRAP = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "localhost:9092",
)

GROUP = os.getenv(
    "KAFKA_CONSUMER_GROUP",
    "estate-gate-consumer-v1",
)

LEDGER_PATH = os.getenv(
    "EVENT_LEDGER_PATH",
    "services/event_consumer/processed_events.db",
)

TOPICS = [
    "gate.entry.v1",
    "gate.exit.v1",
]

running = True


def stop_consumer(signum, frame):
    global running
    running = False
    logger.info("Shutdown requested")


signal.signal(signal.SIGINT, stop_consumer)
signal.signal(signal.SIGTERM, stop_consumer)


class GateEventConsumer:

    def __init__(self):

        self.consumer = Consumer({
            "bootstrap.servers": BOOTSTRAP,
            "group.id": GROUP,
            "client.id": "estate-gate-consumer",

            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,

            "session.timeout.ms": 45000,
            "max.poll.interval.ms": 300000,
        })

        self.ledger = EventLedger(LEDGER_PATH)
        self.django = DjangoGateClient()
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
            "Offset committed: %s partition=%s offset=%s",
            message.topic(),
            message.partition(),
            message.offset(),
        )

    def route_failure(
        self,
        message,
        raw_payload,
        event_id,
        error,
    ):

        if is_transient_error(error):

            envelope = create_retry_envelope(
                raw_payload=raw_payload,
                event_id=event_id,
                attempt=1,
                error=error,
                source_topic=message.topic(),
            )

            self.publisher.publish(
                topic=RETRY_TOPIC,
                key=event_id or envelope["retry_id"],
                payload=envelope,
            )

            logger.warning(
                "Event scheduled for retry: %s",
                event_id,
            )

        else:

            envelope = create_dlq_envelope(
                raw_payload=raw_payload,
                event_id=event_id,
                error=error,
                source_topic=message.topic(),
                attempts=0,
            )

            self.publisher.publish(
                topic="gate.access.dlq.v1",
                key=event_id or envelope["dlq_id"],
                payload=envelope,
            )

            logger.error(
                "Permanent failure sent to DLQ: %s",
                event_id,
            )

    def process_message(self, message):

        raw_payload = message.value().decode("utf-8")
        event_id = None

        try:

            event = GateEvent.model_validate_json(
                raw_payload
            )

            event_id = str(event.event_id)

            expected_topic = (
                "gate.entry.v1"
                if event.direction == "ENTRY"
                else "gate.exit.v1"
            )

            if message.topic() != expected_topic:
                raise ValueError(
                    "Event direction does not match Kafka topic"
                )

        except (ValidationError, ValueError, json.JSONDecodeError) as exc:

            self.route_failure(
                message,
                raw_payload,
                event_id,
                exc,
            )

            self.commit(message)
            return

        if self.ledger.is_processed(event.event_id):

            logger.warning(
                "Duplicate skipped: %s",
                event.event_id,
            )

            self.commit(message)
            return

        try:

            result = self.processor.process_event(event)

            self.ledger.mark_processed(
                event.event_id,
                event.idempotency_key,
            )

            logger.info(
                "Successfully processed event %s",
                event.event_id,
            )

            self.commit(message)

        except requests.RequestException as exc:

            logger.exception(
                "Django request failed: %s",
                event.event_id,
            )

            self.route_failure(
                message,
                raw_payload,
                event_id,
                exc,
            )

            self.commit(message)

        except Exception:

            # Unexpected software or infrastructure error.
            # Do not acknowledge the original Kafka message.
            logger.exception(
                "Unexpected processing error. "
                "Message will remain uncommitted."
            )

            raise

    def run(self):

        self.consumer.subscribe(TOPICS)

        logger.info(
            "Subscribed to %s",
            TOPICS,
        )

        try:

            while running:

                message = self.consumer.poll(1.0)

                if message is None:
                    continue

                if message.error():

                    if message.error().code() == KafkaError._PARTITION_EOF:
                        continue

                    raise RuntimeError(
                        str(message.error())
                    )

                self.process_message(message)

        finally:
            self.close()

    def close(self):

        logger.info("Closing consumer")

        self.consumer.close()
        self.publisher.close()
        self.ledger.close()
        self.django.close()


if __name__ == "__main__":

    try:
        GateEventConsumer().run()

    except Exception:
        logger.exception("Consumer terminated")
        sys.exit(1)
