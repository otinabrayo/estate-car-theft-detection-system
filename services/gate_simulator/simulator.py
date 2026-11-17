import argparse
import json
import logging
import sys

from uuid import uuid4

from confluent_kafka import Producer  # type: ignore[import-not-found]
from pydantic import ValidationError  # type: ignore[import-not-found]

from services.shared.event_contract import GateEvent

from services.gate_simulator.config import (
    KAFKA_BOOTSTRAP_SERVERS,
    ESTATE_ID,
    GATE_ID,
    ENTRY_TOPIC,
    EXIT_TOPIC,
    validate_config,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("gate-simulator")


class GateSimulator:

    def __init__(self):

        validate_config()

        self.producer = Producer({
            "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
            "client.id": "estate-gate-simulator",
            "acks": "all",
            "enable.idempotence": True,
            "retries": 10,
            "max.in.flight.requests.per.connection": 5,
        })

        self.estate_id = ESTATE_ID
        self.gate_id = GATE_ID

    def create_event(
        self,
        direction: str,
        registration: str,
        confidence: float = 0.98,
        duplicate: bool = False,
    ):

        event_id = uuid4()

        event_type = (
            "VEHICLE_ENTRY"
            if direction == "ENTRY"
            else "VEHICLE_EXIT"
        )

        event = GateEvent(
            event_id=event_id,
            event_type=event_type,
            estate_id=self.estate_id,
            gate_id=self.gate_id,
            direction=direction,
            detected_registration=registration.upper(),
            confidence=confidence,
            source="SIMULATOR",
            idempotency_key=event_id,
            metadata={
                "simulator": True,
                "duplicate_test": duplicate,
            },
        )

        return event

    def delivery_report(self, err, msg):

        if err is not None:
            logger.error(
                "Kafka delivery failed: %s",
                err,
            )
            return

        logger.info(
            "Delivered topic=%s partition=%s offset=%s key=%s",
            msg.topic(),
            msg.partition(),
            msg.offset(),
            msg.key().decode("utf-8") if msg.key() else None,
        )

    def publish(self, event: GateEvent):

        topic = (
            ENTRY_TOPIC
            if event.direction == "ENTRY"
            else EXIT_TOPIC
        )

        payload = event.model_dump_json()

        self.producer.produce(
            topic=topic,
            key=str(event.gate_id),
            value=payload.encode("utf-8"),
            callback=self.delivery_report,
        )

        self.producer.poll(0)

        logger.info(
            "Published %s event for %s",
            event.direction,
            event.detected_registration,
        )

    def simulate(
        self,
        direction: str,
        registration: str,
        confidence: float,
        duplicate: bool = False,
    ):

        event = self.create_event(
            direction=direction,
            registration=registration,
            confidence=confidence,
            duplicate=duplicate,
        )

        logger.info(
            "Simulating %s for vehicle %s",
            direction,
            registration,
        )

        self.publish(event)

        if duplicate:
            logger.warning(
                "Publishing duplicate event with the SAME event ID"
            )

            self.publish(event)

        self.producer.flush(15)


def main():

    parser = argparse.ArgumentParser(
        description="Estate vehicle gate simulator"
    )

    parser.add_argument(
        "--direction",
        required=True,
        choices=["ENTRY", "EXIT"],
    )

    parser.add_argument(
        "--plate",
        required=True,
    )

    parser.add_argument(
        "--confidence",
        type=float,
        default=0.98,
    )

    parser.add_argument(
        "--duplicate",
        action="store_true",
    )

    args = parser.parse_args()

    try:
        simulator = GateSimulator()

        simulator.simulate(
            direction=args.direction,
            registration=args.plate,
            confidence=args.confidence,
            duplicate=args.duplicate,
        )

    except (ValidationError, ValueError, RuntimeError) as exc:
        logger.error("Simulation rejected: %s", exc)
        sys.exit(1)

    except Exception:
        logger.exception("Unexpected simulator failure")
        sys.exit(1)


if __name__ == "__main__":
    main()
