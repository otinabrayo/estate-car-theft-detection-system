import logging
import os

from dotenv import load_dotenv

from services.event_consumer.reliability import (
    EventPublisher,
    DLQ_TOPIC,
    create_dlq_envelope,
)


load_dotenv(".env.phase3")

logger = logging.getLogger("dlq-handler")


class DeadLetterPublisher:

    def __init__(self):

        bootstrap = os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS",
            "localhost:9092",
        )

        self.publisher = EventPublisher(bootstrap)

    def send(
        self,
        raw_payload,
        event_id,
        error,
        source_topic,
        attempts=0,
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
            "Event sent to DLQ | ID=%s | Attempts=%s",
            event_id,
            attempts,
        )

    def close(self):
        self.publisher.close()
