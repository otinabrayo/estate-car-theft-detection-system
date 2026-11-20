import json
import logging
import os

import requests

logger = logging.getLogger(__name__)


class VerificationServiceError(requests.RequestException):
    """Verification service returned an invalid response."""


class VerificationServiceClient:

    def __init__(self):
        self.base_url = os.getenv(
            "VERIFICATION_SERVICE_URL",
            "http://127.0.0.1:8002/api/v1",
        ).rstrip("/")

        self.timeout = float(
            os.getenv("VERIFICATION_SERVICE_TIMEOUT", "15")
        )

    @staticmethod
    def serialize_event(event) -> dict:
        """Support Pydantic v1, Pydantic v2, and dictionaries."""

        if hasattr(event, "model_dump"):
            return event.model_dump(mode="json")

        if hasattr(event, "json"):
            return json.loads(event.json())

        if isinstance(event, dict):
            return event

        raise VerificationServiceError(
            "Unsupported event type. Expected a Pydantic "
            "GateEvent or dictionary."
        )

    def verify_event(self, event) -> dict:
        url = f"{self.base_url}/verification/events/"
        payload = self.serialize_event(event)

        response = None

        event_id = payload.get("event_id")
        idempotency_key = payload.get("idempotency_key")

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout,
            )

            if response.status_code == 409:
                try:
                    body = response.json()
                    detail = body.get("detail", body)
                except ValueError:
                    detail = response.text[:2000]

                logger.warning(
                    "Verification conflict: event_id=%s "
                    "idempotency_key=%s status=%s detail=%s",
                    event_id,
                    idempotency_key,
                    response.status_code,
                    detail,
                )

                if (
                    isinstance(detail, str)
                    and "already being processed" in detail.lower()
                ):
                    raise requests.Timeout(
                        "Verification event is still being processed."
                    )

            response.raise_for_status()

            result = response.json()

            required_fields = {
                "event_id",
                "idempotency_key",
                "verification_status",
                "accepted",
                "risk_score",
                "risk_level",
            }

            missing_fields = required_fields.difference(result.keys())

            if missing_fields:
                raise VerificationServiceError(
                    "Verification response missing fields: "
                    + ", ".join(sorted(missing_fields))
                )

            logger.info(
                "Verification result: event=%s status=%s "
                "risk=%s level=%s",
                result["event_id"],
                result["verification_status"],
                result["risk_score"],
                result["risk_level"],
            )

            return result

        except requests.Timeout:
            logger.warning(
                "Verification request timed out: event_id=%s",
                event_id,
            )
            raise

        except requests.ConnectionError:
            logger.exception(
                "Verification service is unavailable: event_id=%s",
                event_id,
            )
            raise

        except requests.HTTPError as exc:
            error_response = exc.response or response

            logger.error(
                "Verification HTTP error: event_id=%s "
                "idempotency_key=%s status=%s url=%s body=%s",
                event_id,
                idempotency_key,
                error_response.status_code if error_response else "unknown",
                error_response.url if error_response else url,
                error_response.text[:2000]
                if error_response is not None
                else "No response body",
            )
            raise

        except requests.RequestException:
            logger.exception(
                "Verification service request failed: event_id=%s",
                event_id,
            )
            raise

    def get_owner_confirmation_status(
        self,
        event_id: str,
    ) -> dict:
        url = (
            f"{self.base_url}"
            f"/verification/owner-confirmations/{event_id}/"
        )

        response = requests.get(
            url,
            timeout=self.timeout,
        )

        response.raise_for_status()

        return response.json()
