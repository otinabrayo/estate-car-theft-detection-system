from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.alerts.models import OwnerConfirmationRequest
from apps.alerts.services import create_owner_confirmation_alert

class OwnerConfirmationEscalationTests(TestCase):

    def setUp(self):
        self.confirmation = cast(OwnerConfirmationRequest, SimpleNamespace(
            id="confirmation-123",
            status="REJECTED",
            idempotency_key="idempotency-123",
            estate_id="estate-123",
            estate=SimpleNamespace(id="estate-123"),
            vehicle_id="vehicle-123",
            gate_id="gate-123",
            direction="ENTRY",
            detected_registration="KCP697S",
            risk_score=80,
            event_id="event-123",
        ))

        self.access_event = SimpleNamespace(
            id="access-event-123",
            movement_session=None,
        )

    @patch("apps.alerts.services.SecurityAlert.objects.get_or_create")
    @patch("apps.alerts.services.GateAccessEvent.objects")
    def test_rejection_creates_critical_alert(
        self,
        access_event_manager,
        alert_manager,
    ):
        access_event_manager.select_for_update.return_value.filter.return_value.first.return_value = (
            self.access_event
        )

        alert_manager.return_value = (
            SimpleNamespace(
                id="alert-123",
                severity="CRITICAL",
                status="OPEN",
                rule_code="OWNER_REJECTED_VEHICLE",
            ),
            True,
        )

        alert = create_owner_confirmation_alert(
            self.confirmation
        )

        assert alert is not None
        self.assertEqual(alert.severity, "CRITICAL")
        self.assertEqual(alert.status, "OPEN")

        kwargs = alert_manager.call_args.kwargs
        self.assertEqual(
            kwargs["rule_code"],
            "OWNER_REJECTED_VEHICLE",
        )

    @patch("apps.alerts.services.SecurityAlert.objects.get_or_create")
    @patch("apps.alerts.services.GateAccessEvent.objects")
    def test_high_risk_expiration_creates_high_alert(
        self,
        access_event_manager,
        alert_manager,
    ):
        self.confirmation.status = "EXPIRED"
        self.confirmation.risk_score = 60

        access_event_manager.select_for_update.return_value.filter.return_value.first.return_value = (
            self.access_event
        )

        alert_manager.return_value = (
            SimpleNamespace(
                id="alert-456",
                severity="HIGH",
                status="OPEN",
                rule_code="OWNER_CONFIRMATION_EXPIRED",
            ),
            True,
        )

        alert = create_owner_confirmation_alert(
            self.confirmation
        )

        assert alert is not None
        self.assertEqual(alert.severity, "HIGH")
        self.assertEqual(
            alert.rule_code,
            "OWNER_CONFIRMATION_EXPIRED",
        )

    def test_low_risk_expiration_does_not_create_alert(self):
        self.confirmation.status = "EXPIRED"
        self.confirmation.risk_score = 20

        with patch(
            "apps.alerts.services.GateAccessEvent.objects"
        ) as access_event_manager:
            alert = create_owner_confirmation_alert(
                self.confirmation
            )

        self.assertIsNone(alert)
        access_event_manager.select_for_update.assert_not_called()

    def test_confirmed_request_does_not_create_alert(self):
        self.confirmation.status = "CONFIRMED"

        with patch(
            "apps.alerts.services.GateAccessEvent.objects"
        ) as access_event_manager:
            alert = create_owner_confirmation_alert(
                self.confirmation
            )

        self.assertIsNone(alert)
        access_event_manager.select_for_update.assert_not_called()

    @patch("apps.alerts.services.SecurityAlert.objects.get_or_create")
    @patch("apps.alerts.services.GateAccessEvent.objects")
    def test_missing_access_event_does_not_create_alert(
        self,
        access_event_manager,
        alert_manager,
    ):
        access_event_manager.select_for_update.return_value.filter.return_value.first.return_value = (
            None
        )

        alert = create_owner_confirmation_alert(
            self.confirmation
        )

        self.assertIsNone(alert)
        alert_manager.assert_not_called()
