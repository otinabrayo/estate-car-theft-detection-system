import os
import logging

import requests

from dotenv import load_dotenv

from services.shared.event_contract import GateEvent


load_dotenv(".env.phase3")

logger = logging.getLogger("django-client")


class DjangoGateClient:

    def __init__(self):

        self.base_url = os.getenv(
            "DJANGO_API_BASE_URL",
            "http://127.0.0.1:8000",
        ).rstrip("/")

        token = os.getenv("DJANGO_API_TOKEN")

        if not token:
            raise RuntimeError(
                "DJANGO_API_TOKEN is missing"
            )

        self.session = requests.Session()

        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

        self.timeout = 15

    def process_event(self, event: GateEvent):

        endpoint = (
            "/api/v1/gate-access/entry/"
            if event.direction == "ENTRY"
            else "/api/v1/gate-access/exit/"
        )

        payload = {
            "estate": str(event.estate_id),
            "gate": str(event.gate_id),
            "registration_number": event.detected_registration,
            "confidence": event.confidence,
            "source": "API",
            "idempotency_key": str(event.idempotency_key),
        }

        if (
            event.direction == "ENTRY"
            and event.visitor_pass_code
        ):
            payload["visitor_pass_code"] = (
                event.visitor_pass_code
            )

        if event.evidence_object_key:
            payload["evidence_object_key"] = (
                event.evidence_object_key
            )

        url = f"{self.base_url}{endpoint}"

        logger.info(
            "Sending %s event for %s to Django",
            event.direction,
            event.detected_registration,
        )

        response = self.session.post(
            url,
            json=payload,
            timeout=self.timeout,
        )

        if not response.ok:
            logger.error(
                "Django rejected event. Status=%s Body=%s",
                response.status_code,
                response.text[:1000],
            )

        response.raise_for_status()

        try:
            result = response.json()
        except ValueError:
            result = {"detail": response.text}

        logger.info(
            "Django processed %s event. HTTP %s",
            event.direction,
            response.status_code,
        )

        return result

    def close(self):
        self.session.close()
