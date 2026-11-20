import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[3]

# Load shared project environment first.
load_dotenv(ROOT_DIR / ".env", override=False)

# Load Phase 5 settings.
load_dotenv(ROOT_DIR / ".env.phase5", override=True)

INTERNAL_SERVICE_TOKEN = os.getenv(
    "DJANGO_INTERNAL_SERVICE_TOKEN",
    ""
)

class Settings:
    SERVICE_NAME = os.getenv(
        "VERIFICATION_SERVICE_NAME",
        "estate-verification-service"
    )

    HOST = os.getenv("VERIFICATION_SERVICE_HOST", "127.0.0.1")
    PORT = int(os.getenv("VERIFICATION_SERVICE_PORT", "8002"))

    DEBUG = os.getenv(
        "VERIFICATION_DEBUG",
        "false"
    ).lower() == "true"

    DJANGO_API_BASE_URL = os.getenv(
        "DJANGO_API_BASE_URL",
        "http://127.0.0.1:8000"
    ).rstrip("/")

    REDIS_URL = os.getenv(
        "REDIS_URL",
        "redis://localhost:6380/1"
    )

    INTERNAL_SERVICE_TOKEN = os.getenv(
        "DJANGO_INTERNAL_SERVICE_TOKEN",
        ""
    )


settings = Settings()
