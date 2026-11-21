from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.estates.models import Estate, Gate
from apps.access_control.models import GateAccessEvent
from apps.alerts.engine import (
    REPEATED_ATTEMPT_THRESHOLD,
    REPEATED_ATTEMPT_WINDOW_MINUTES,
    count_recent_attempts,
    evaluate_gate_event,
)
from apps.alerts.models import SecurityAlert

User = get_user_model()

class AlertEngineTests(TestCase):



    def setUp(self):
        self.estate = Estate.objects.create(
            name="Alert Engine Estate",
            address="Nairobi",
            city="Nairobi",
            county="Nairobi",
            country="Kenya",
        )

        self.gate = Gate.objects.create(
            estate=self.estate,
            name="Main Gate",
            code="MAIN",
        )

        self.recorded_by = User.objects.create_user(   # type: ignore
            email="alert-engine-admin@test.com",
            password="test-password",
            role="ESTATE_ADMIN",
        )

    def create_event(
        self,
        *,
        registration="KCA123A",
        reason="Routine access event.",
        direction=GateAccessEvent.Direction.ENTRY,
        decision=GateAccessEvent.Decision.DENIED,
        occurred_at=None,
        confidence=None,
        estate=None,
    ):
        return GateAccessEvent.objects.create(
            estate=estate or self.estate,
            gate=self.gate,
            direction=direction,
            decision=decision,
            detected_registration=registration,
            confidence=confidence,
            reason=reason,
            source=GateAccessEvent.Source.MANUAL,
            recorded_by=self.recorded_by,
            occurred_at=occurred_at or timezone.now(),
        )

    def assert_alert_created(
        self,
        event,
        rule_code,
        severity,
    ):
        alerts = evaluate_gate_event(event)

        matching_alerts = [
            alert for alert in alerts
            if alert.rule_code == rule_code
        ]

        self.assertEqual(len(matching_alerts), 1)

        alert = matching_alerts[0]

        self.assertEqual(alert.access_event, event)
        self.assertEqual(alert.estate, event.estate)
        self.assertEqual(alert.severity, severity)

        return alert

    # --------------------------------------------------
    # INDIVIDUAL DETECTION RULES
    # --------------------------------------------------

    def test_unknown_vehicle_creates_high_alert(self):
        event = self.create_event(
            reason="Vehicle is not registered in this estate."
        )

        alert = self.assert_alert_created(
            event,
            SecurityAlert.RuleCode.UNKNOWN_VEHICLE,
            SecurityAlert.Severity.HIGH,
        )

        self.assertEqual(
            alert.title,
            "Unregistered vehicle attempted entry",
        )

    def test_invalid_visitor_pass_creates_high_alert(self):
        event = self.create_event(
            reason="Visitor pass has expired."
        )

        self.assert_alert_created(
            event,
            SecurityAlert.RuleCode.INVALID_VISITOR_PASS,
            SecurityAlert.Severity.HIGH,
        )

    def test_plate_mismatch_creates_high_alert(self):
        event = self.create_event(
            reason="Detected registration does not match visitor pass."
        )

        self.assert_alert_created(
            event,
            SecurityAlert.RuleCode.PLATE_MISMATCH,
            SecurityAlert.Severity.HIGH,
        )

    def test_unmatched_exit_creates_critical_alert(self):
        event = self.create_event(
            direction=GateAccessEvent.Direction.EXIT,
            decision=GateAccessEvent.Decision.REVIEW,
            reason=(
                "Exit attempted without a matching active entry session."
            ),
        )

        self.assert_alert_created(
            event,
            SecurityAlert.RuleCode.UNMATCHED_EXIT,
            SecurityAlert.Severity.CRITICAL,
        )

    def test_unmatched_exit_reason_does_not_trigger_on_entry(self):
        event = self.create_event(
            direction=GateAccessEvent.Direction.ENTRY,
            reason=(
                "Exit attempted without a matching active entry session."
            ),
        )

        alerts = evaluate_gate_event(event)

        self.assertFalse(
            any(
                alert.rule_code == SecurityAlert.RuleCode.UNMATCHED_EXIT
                for alert in alerts
            )
        )

    def test_duplicate_entry_creates_high_alert(self):
        event = self.create_event(
            reason="Vehicle already has an open movement session."
        )

        self.assert_alert_created(
            event,
            SecurityAlert.RuleCode.DUPLICATE_ENTRY,
            SecurityAlert.Severity.HIGH,
        )

    def test_low_anpr_confidence_creates_medium_alert(self):
        event = self.create_event(
            reason="ANPR confidence is below the configured threshold.",
            decision=GateAccessEvent.Decision.REVIEW,
            confidence="0.6500",
        )

        alert = self.assert_alert_created(
            event,
            SecurityAlert.RuleCode.LOW_ANPR_CONFIDENCE,
            SecurityAlert.Severity.MEDIUM,
        )

        self.assertEqual(
            alert.metadata["confidence"],
            "0.6500",
        )

    def test_low_anpr_confidence_handles_missing_confidence(self):
        event = self.create_event(
            reason="ANPR confidence is below the configured threshold.",
            decision=GateAccessEvent.Decision.REVIEW,
        )

        alert = self.assert_alert_created(
            event,
            SecurityAlert.RuleCode.LOW_ANPR_CONFIDENCE,
            SecurityAlert.Severity.MEDIUM,
        )

        self.assertIsNone(alert.metadata["confidence"])

    # --------------------------------------------------
    # REPEATED ACCESS ATTEMPTS
    # --------------------------------------------------

    def test_repeated_denials_create_alert_at_threshold(self):
        current_time = timezone.now()

        self.create_event(
            occurred_at=current_time - timedelta(minutes=5),
        )

        self.create_event(
            occurred_at=current_time - timedelta(minutes=2),
            decision=GateAccessEvent.Decision.REVIEW,
        )

        current_event = self.create_event(
            occurred_at=current_time,
        )

        alert = self.assert_alert_created(
            current_event,
            SecurityAlert.RuleCode.REPEATED_DENIALS,
            SecurityAlert.Severity.HIGH,
        )

        self.assertEqual(alert.metadata["attempt_count"], 3)
        self.assertEqual(
            alert.metadata["window_minutes"],
            REPEATED_ATTEMPT_WINDOW_MINUTES,
        )

    def test_repeated_denials_do_not_trigger_below_threshold(self):
        current_time = timezone.now()

        self.create_event(
            occurred_at=current_time - timedelta(minutes=2),
        )

        current_event = self.create_event(
            occurred_at=current_time,
        )

        self.assertEqual(
            count_recent_attempts(current_event),
            REPEATED_ATTEMPT_THRESHOLD - 1,
        )

        alerts = evaluate_gate_event(current_event)

        self.assertFalse(
            any(
                alert.rule_code == SecurityAlert.RuleCode.REPEATED_DENIALS
                for alert in alerts
            )
        )

    def test_repeated_denials_include_event_at_window_boundary(self):
        current_time = timezone.now()

        boundary_time = current_time - timedelta(
            minutes=REPEATED_ATTEMPT_WINDOW_MINUTES
        )

        self.create_event(occurred_at=boundary_time)

        self.create_event(
            occurred_at=current_time - timedelta(minutes=5),
        )

        current_event = self.create_event(
            occurred_at=current_time,
        )

        self.assertEqual(
            count_recent_attempts(current_event),
            REPEATED_ATTEMPT_THRESHOLD,
        )

        alerts = evaluate_gate_event(current_event)

        self.assertTrue(
            any(
                alert.rule_code == SecurityAlert.RuleCode.REPEATED_DENIALS
                for alert in alerts
            )
        )

    def test_repeated_denials_exclude_events_before_window(self):
        current_time = timezone.now()

        outside_window = current_time - timedelta(
            minutes=REPEATED_ATTEMPT_WINDOW_MINUTES,
            seconds=1,
        )

        self.create_event(occurred_at=outside_window)

        self.create_event(
            occurred_at=current_time - timedelta(minutes=5),
        )

        current_event = self.create_event(
            occurred_at=current_time,
        )

        self.assertEqual(
            count_recent_attempts(current_event),
            2,
        )

        alerts = evaluate_gate_event(current_event)

        self.assertFalse(
            any(
                alert.rule_code == SecurityAlert.RuleCode.REPEATED_DENIALS
                for alert in alerts
            )
        )

    def test_repeated_denials_ignore_allowed_events(self):
        current_time = timezone.now()

        self.create_event(
            occurred_at=current_time - timedelta(minutes=5),
            decision=GateAccessEvent.Decision.ALLOWED,
        )

        self.create_event(
            occurred_at=current_time - timedelta(minutes=2),
        )

        current_event = self.create_event(
            occurred_at=current_time,
        )

        self.assertEqual(
            count_recent_attempts(current_event),
            2,
        )

    def test_repeated_denials_are_scoped_to_estate_and_registration(self):
        current_time = timezone.now()

        other_estate = Estate.objects.create(
            name="Another Alert Estate",
            address="Mombasa",
            city="Mombasa",
            county="Mombasa",
            country="Kenya",
        )

        other_gate = Gate.objects.create(
            estate=other_estate,
            name="Other Gate",
            code="OTHER",
        )

        GateAccessEvent.objects.create(
            estate=other_estate,
            gate=other_gate,
            direction=GateAccessEvent.Direction.ENTRY,
            decision=GateAccessEvent.Decision.DENIED,
            detected_registration="KCA123A",
            reason="Denied.",
            source=GateAccessEvent.Source.MANUAL,
            recorded_by=self.recorded_by,
            occurred_at=current_time - timedelta(minutes=5),
        )

        self.create_event(
            registration="KCB456B",
            occurred_at=current_time - timedelta(minutes=4),
        )

        current_event = self.create_event(
            occurred_at=current_time,
        )

        self.assertEqual(
            count_recent_attempts(current_event),
            1,
        )

    # --------------------------------------------------
    # IDEMPOTENCY
    # --------------------------------------------------

    def test_evaluating_same_event_twice_does_not_duplicate_alert(self):
        event = self.create_event(
            reason="Vehicle is not registered in this estate."
        )

        first_result = evaluate_gate_event(event)
        second_result = evaluate_gate_event(event)

        self.assertEqual(len(first_result), 1)
        self.assertEqual(len(second_result), 1)

        self.assertEqual(
            first_result[0].pk,
            second_result[0].pk,
        )

        self.assertEqual(
            SecurityAlert.objects.filter(
                access_event=event,
                rule_code=SecurityAlert.RuleCode.UNKNOWN_VEHICLE,
            ).count(),
            1,
        )
