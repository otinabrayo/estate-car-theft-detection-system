import os
from pathlib import Path

from dotenv import load_dotenv


# Project root:
# estate-car-theft-detection-system/
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Load existing Docker credentials first.
load_dotenv(PROJECT_ROOT / ".env")

# Load Phase 4 service configuration.
load_dotenv(PROJECT_ROOT / ".env.phase4", override=True)

KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "localhost:9092",
)

KAFKA_ENTRY_TOPIC = os.getenv(
    "KAFKA_ENTRY_TOPIC",
    "gate.entry.v1",
)

KAFKA_EXIT_TOPIC = os.getenv(
    "KAFKA_EXIT_TOPIC",
    "gate.exit.v1",
)

MAX_VIDEO_SIZE_MB = int(os.getenv("MAX_VIDEO_SIZE_MB", "100"))
MAX_VIDEO_SIZE_BYTES = MAX_VIDEO_SIZE_MB * 1024 * 1024

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD")

MINIO_BUCKET = os.getenv(
    "MINIO_BUCKET",
    "estate-vehicle-evidence",
)

MINIO_SECURE = (
    os.getenv("MINIO_SECURE", "false").lower() == "true"
)

MAX_IMAGE_SIZE_MB = int(
    os.getenv("MAX_IMAGE_SIZE_MB", "30")
)

MAX_IMAGE_SIZE_BYTES = MAX_IMAGE_SIZE_MB * 1024 * 1024

if not MINIO_ACCESS_KEY or not MINIO_SECRET_KEY:
    raise RuntimeError(
        "MinIO credentials are missing. "
        "Check MINIO_ROOT_USER and MINIO_ROOT_PASSWORD in .env."
    )
