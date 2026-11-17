import os

from dotenv import load_dotenv

load_dotenv(".env.phase3")


KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "localhost:9092",
)

ESTATE_ID = os.getenv("ESTATE_ID")

GATE_ID = os.getenv("GATE_ID")


ENTRY_TOPIC = "gate.entry.v1"

EXIT_TOPIC = "gate.exit.v1"


def validate_config():
    missing = []

    if not ESTATE_ID:
        missing.append("ESTATE_ID")

    if not GATE_ID:
        missing.append("GATE_ID")

    if missing:
        raise RuntimeError(
            f"Missing simulator configuration: {', '.join(missing)}"
        )
