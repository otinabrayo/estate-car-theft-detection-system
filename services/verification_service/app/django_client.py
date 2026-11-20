import httpx

from .config import settings


class DjangoServiceError(Exception):
    pass


async def lookup_vehicle_session(
    estate_id: str,
    registration_number: str,
    gate_id: str | None = None,
    visitor_pass_code: str | None = None,
    direction: str = "ENTRY",
) -> dict:

    if not settings.INTERNAL_SERVICE_TOKEN:
        raise DjangoServiceError(
            "Django internal service token is not configured."
        )

    url = (
        f"{settings.DJANGO_API_BASE_URL}"
        "/api/v1/internal/vehicles/session-lookup/"
    )

    headers = {
        "X-Internal-Service-Token": (
            settings.INTERNAL_SERVICE_TOKEN
        )
    }

    params = {
        "estate_id": estate_id,
        "registration_number": registration_number,
        "direction": direction,
    }

    if gate_id:
        params["gate_id"] = gate_id

    if visitor_pass_code:
        params["visitor_pass_code"] = visitor_pass_code

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0)
        ) as client:

            response = await client.get(
                url,
                headers=headers,
                params=params,
            )

            response.raise_for_status()

            return response.json()

    except httpx.TimeoutException as exc:
        raise DjangoServiceError(
            "Django API request timed out."
        ) from exc

    except httpx.ConnectError as exc:
        raise DjangoServiceError(
            "Could not connect to Django API."
        ) from exc

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code

        if status_code == 404:
            raise DjangoServiceError(
                "The requested estate was not found."
            ) from exc

        if status_code in (401, 403):
            raise DjangoServiceError(
                "Django rejected internal service authentication."
            ) from exc

        raise DjangoServiceError(
            f"Django API returned HTTP {status_code}."
        ) from exc

    except httpx.RequestError as exc:
        raise DjangoServiceError(
            "An error occurred while communicating with Django."
        ) from exc


async def create_owner_confirmation_request(
    payload: dict,
) -> dict:
    """
    Create an owner confirmation request through Django.
    """

    if not settings.INTERNAL_SERVICE_TOKEN:
        raise DjangoServiceError(
            "Django internal service token is not configured."
        )

    url = (
        f"{settings.DJANGO_API_BASE_URL}"
        "/api/v1/internal/owner-confirmations/"
    )

    headers = {
        "X-Internal-Service-Token": (
            settings.INTERNAL_SERVICE_TOKEN
        )
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0)
        ) as client:

            response = await client.post(
                url,
                headers=headers,
                json=payload,
            )

            response.raise_for_status()

            return response.json()

    except httpx.TimeoutException as exc:
        raise DjangoServiceError(
            "Django owner confirmation request timed out."
        ) from exc

    except httpx.ConnectError as exc:
        raise DjangoServiceError(
            "Could not connect to Django owner confirmation API."
        ) from exc

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code

        if status_code in (401, 403):
            message = (
                "Django rejected internal service authentication."
            )
        elif status_code == 404:
            message = (
                "The estate, gate, or registered vehicle was not found."
            )
        elif status_code == 409:
            message = (
                "The recognition event conflicts with an existing "
                "owner confirmation request."
            )
        elif status_code == 400:
            message = (
                "Django rejected the owner confirmation data."
            )
        else:
            message = (
                f"Django owner confirmation API returned "
                f"HTTP {status_code}."
            )

        raise DjangoServiceError(message) from exc

    except httpx.RequestError as exc:
        raise DjangoServiceError(
            "An error occurred while creating the owner confirmation."
        ) from exc


async def get_owner_confirmation_status(event_id: str) -> dict:
    """
    Retrieve an owner's confirmation response from Django
    using the recognition event ID.
    """

    if not settings.INTERNAL_SERVICE_TOKEN:
        raise DjangoServiceError(
            "Django internal service token is not configured."
        )

    url = (
        f"{settings.DJANGO_API_BASE_URL}"
        f"/api/v1/internal/owner-confirmations/{event_id}/"
    )

    headers = {
        "X-Internal-Service-Token": settings.INTERNAL_SERVICE_TOKEN
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0)
        ) as client:
            response = await client.get(
                url,
                headers=headers,
            )

            response.raise_for_status()
            return response.json()

    except httpx.TimeoutException as exc:
        raise DjangoServiceError(
            "Django owner confirmation status request timed out."
        ) from exc

    except httpx.ConnectError as exc:
        raise DjangoServiceError(
            "Could not connect to Django owner confirmation API."
        ) from exc

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code

        if status_code in (401, 403):
            message = "Django rejected internal service authentication."
        elif status_code == 404:
            message = "Owner confirmation request was not found."
        else:
            message = (
                f"Django owner confirmation API returned "
                f"HTTP {status_code}."
            )

        raise DjangoServiceError(message) from exc

    except httpx.RequestError as exc:
        raise DjangoServiceError(
            "An error occurred while retrieving owner confirmation status."
        ) from exc
