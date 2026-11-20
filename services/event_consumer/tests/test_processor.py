from unittest.mock import Mock

import pytest

from services.event_consumer.processor import EventProcessor

@pytest.fixture
def event():
    return Mock(
        event_id="11111111-1111-4111-8111-111111111111",
        direction="ENTRY",
    )

@pytest.fixture
def verification_result():
    return {
        "event_id": "11111111-1111-4111-8111-111111111111",
        "idempotency_key": "22222222-2222-4222-8222-222222222222",
        "verification_status": "ALLOW",
        "accepted": True,
        "risk_score": 0,
        "risk_level": "LOW",
        "owner_confirmation_required": False,
    }

def test_processor_calls_verification_before_django(
    event,
    verification_result,
):
    calls = []

    verification_client = Mock()
    django_client = Mock()

    verification_client.verify_event.side_effect = (
        lambda _event: (
            calls.append("verification"),
            verification_result,
        )[1]
    )

    django_client.process_event.side_effect = (
        lambda _event: (
            calls.append("django"),
            {"decision": "ALLOWED"},
        )[1]
    )

    processor = EventProcessor(
        django_client=django_client,
        verification_client=verification_client,
    )

    result = processor.process_event(event)

    assert calls == ["verification", "django"]
    assert result == {"decision": "ALLOWED"}

def test_processor_does_not_call_django_if_verification_fails(
    event,
):
    verification_client = Mock()
    django_client = Mock()

    verification_client.verify_event.side_effect = (
        ConnectionError("Verification unavailable")
    )

    processor = EventProcessor(
        django_client=django_client,
        verification_client=verification_client,
    )

    with pytest.raises(ConnectionError):
        processor.process_event(event)

    django_client.process_event.assert_not_called()

def test_processor_retrieves_rejected_owner_response():
    verification_client = Mock()

    verification_client.get_owner_confirmation_status.return_value = {
        "status": "REJECTED",
        "event_id": "11111111-1111-4111-8111-111111111111",
    }

    processor = EventProcessor(
        django_client=Mock(),
        verification_client=verification_client,
    )

    result = processor.get_owner_review(
        "11111111-1111-4111-8111-111111111111"
    )

    assert result["status"] == "REJECTED"
    