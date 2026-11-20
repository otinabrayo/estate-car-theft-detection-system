from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException   # type: ignore
from unittest.mock import AsyncMock

from services.verification_service.app import routes
from services.verification_service.app.schemas import (
    OwnerConfirmationStatusResponse,
)

@pytest.mark.asyncio
async def test_owner_confirmation_status_returns_confirmed(
    monkeypatch,
):
    event_id = uuid4()

    expected = {
        "id": str(uuid4()),
        "event_id": str(event_id),
        "status": "CONFIRMED",
        "expires_at": datetime.now(timezone.utc).isoformat(),
        "responded_at": datetime.now(timezone.utc).isoformat(),
        "response_note": "Vehicle movement confirmed.",
    }

    mock_lookup = AsyncMock(return_value=expected)

    monkeypatch.setattr(
        routes,
        "get_owner_confirmation_status",
        mock_lookup,
    )

    result = await routes.retrieve_owner_confirmation_status(
        event_id
    )

    assert isinstance(
        result,
        OwnerConfirmationStatusResponse,
    )
    assert result.status == "CONFIRMED"
    assert result.event_id == event_id

    mock_lookup.assert_awaited_once_with(str(event_id))

@pytest.mark.asyncio
async def test_owner_confirmation_status_handles_missing_request(
    monkeypatch,
):
    event_id = uuid4()

    async def missing_request(_event_id):
        raise routes.DjangoServiceError(
            "Owner confirmation request was not found."
        )

    monkeypatch.setattr(
        routes,
        "get_owner_confirmation_status",
        missing_request,
    )

    with pytest.raises(HTTPException) as exc_info:
        await routes.retrieve_owner_confirmation_status(
            event_id
        )

    assert exc_info.value.status_code == 404

@pytest.mark.asyncio
async def test_owner_confirmation_status_handles_django_failure(
    monkeypatch,
):
    event_id = uuid4()

    async def django_failure(_event_id):
        raise routes.DjangoServiceError(
            "Django API request timed out."
        )

    monkeypatch.setattr(
        routes,
        "get_owner_confirmation_status",
        django_failure,
    )

    with pytest.raises(HTTPException) as exc_info:
        await routes.retrieve_owner_confirmation_status(
            event_id
        )

    assert exc_info.value.status_code == 502