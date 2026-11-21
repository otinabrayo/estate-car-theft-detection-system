from django.contrib.auth import get_user_model
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.estates.models import Estate, EstateMembership, Gate
from apps.access_control.models import GateAccessEvent
from apps.alerts.models import SecurityAlert
from apps.incidents.models import Incident, IncidentAlert, IncidentActivity

User = get_user_model()

class IncidentAlertLinkingTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(   # type: ignore
            email="security-link@example.com",
            password="TestPassword123!",
        )

        self.estate = Estate.objects.create(
            name="Linking Estate",
            address="Nairobi",
            city="Nairobi",
            county="Nairobi",
        )

        EstateMembership.objects.create(
            user=self.user,
            estate=self.estate,
            role=EstateMembership.Role.SECURITY,
            is_active=True,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.incident = Incident.objects.create(
            estate=self.estate,
            incident_type=Incident.IncidentType.THEFT_SUSPECTED,
            severity=Incident.Severity.HIGH,
            title="Suspected vehicle theft",
            description="Suspicious exit detected.",
            created_by=self.user,
        )

        self.gate = Gate.objects.create(
            estate=self.estate,
            name="Main Gate",
            code="MAIN-LINK",
        )

        self.event = GateAccessEvent.objects.create(
            estate=self.estate,
            gate=self.gate,
            recorded_by=self.user,  # Required field
            direction=GateAccessEvent.Direction.EXIT,
            decision=GateAccessEvent.Decision.REVIEW,
            detected_registration="KDA123A",
            reason="Exit attempted without a matching active entry session.",
            source=GateAccessEvent.Source.MANUAL,
        )

        self.alert = SecurityAlert.objects.create(
            estate=self.estate,
            access_event=self.event,
            rule_code=SecurityAlert.RuleCode.UNMATCHED_EXIT,
            severity=SecurityAlert.Severity.CRITICAL,
            title="Unmatched vehicle exit",
            description="Vehicle exit has no matching entry.",
            detected_registration="KDA123A",
        )

        self.url = reverse(
            "incident-link-alert",
            kwargs={"pk": self.incident.pk},
        )

    def test_alert_can_be_linked_to_incident(self):
        response = self.client.post(
            self.url,
            {"alert_id": str(self.alert.id)},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertTrue(
            IncidentAlert.objects.filter(
                incident=self.incident,
                alert=self.alert,
            ).exists()
        )

        self.assertTrue(
            IncidentActivity.objects.filter(
                incident=self.incident,
                action=IncidentActivity.Action.ALERT_LINKED,
            ).exists()
        )

        # Linking must not change the alert lifecycle.
        self.alert.refresh_from_db()
        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.OPEN,
        )

    def test_alert_cannot_be_linked_twice(self):
        self.client.post(
            self.url,
            {"alert_id": str(self.alert.id)},
            format="json",
        )

        response = self.client.post(
            self.url,
            {"alert_id": str(self.alert.id)},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(
            IncidentAlert.objects.filter(alert=self.alert).count(),
            1,
        )

    def test_alert_cannot_be_linked_across_estates(self):
        other_estate = Estate.objects.create(
            name="Different Estate",
            address="Mombasa",
            city="Mombasa",
            county="Mombasa",
        )

        other_gate = Gate.objects.create(
            estate=other_estate,
            name="Other Gate",
            code="OTHER-LINK",
        )

        other_event = GateAccessEvent.objects.create(
            estate=other_estate,
            gate=other_gate,
            recorded_by=self.user,  # Required field
            direction=GateAccessEvent.Direction.EXIT,
            decision=GateAccessEvent.Decision.REVIEW,
            detected_registration="KDB456B",
            reason="Unmatched exit.",
            source=GateAccessEvent.Source.MANUAL,
        )

        other_alert = SecurityAlert.objects.create(
            estate=other_estate,
            access_event=other_event,
            rule_code=SecurityAlert.RuleCode.UNMATCHED_EXIT,
            severity=SecurityAlert.Severity.CRITICAL,
            title="Other estate alert",
            description="Other estate vehicle exit.",
        )

        response = self.client.post(
            self.url,
            {"alert_id": str(other_alert.id)},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

        self.assertFalse(
            IncidentAlert.objects.filter(alert=other_alert).exists()
        )