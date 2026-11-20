import uuid
from typing import cast

from django.contrib.auth import get_user_model
from django.http.response import HttpResponseBase
from django.urls import reverse
from django.test import TestCase

from rest_framework.test import APIClient

from apps.estates.models import Estate, EstateMembership, Gate
from apps.access_control.models import GateAccessEvent
from apps.alerts.models import SecurityAlert


User = get_user_model()


class SecurityAlertAssignmentTests(TestCase):

    def setUp(self):
        self.api_client = APIClient()

        self.estate = Estate.objects.create(
            name="Test Estate",
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

        self.estate_admin = User.objects.create_user(   # type: ignore
            email="admin@test.com",
            password="test-password",
            role="ESTATE_ADMIN",
        )

        self.security = User.objects.create_user(        # type: ignore
            email="security@test.com",
            password="test-password",
            role="SECURITY",
        )

        self.outsider = User.objects.create_user(        # type: ignore
            email="outsider@test.com",
            password="test-password",
            role="SECURITY",
        )

        EstateMembership.objects.create(
            estate=self.estate,
            user=self.estate_admin,
            role=EstateMembership.Role.ESTATE_ADMIN,
            is_active=True,
        )

        EstateMembership.objects.create(
            estate=self.estate,
            user=self.security,
            role=EstateMembership.Role.SECURITY,
            is_active=True,
        )

        self.access_event = GateAccessEvent.objects.create(
            estate=self.estate,
            gate=self.gate,
            direction=GateAccessEvent.Direction.ENTRY,
            decision=GateAccessEvent.Decision.DENIED,
            detected_registration="KCA123A",
            reason="Unknown vehicle.",
            source=GateAccessEvent.Source.MANUAL,
            recorded_by=self.estate_admin,
        )

        self.alert = SecurityAlert.objects.create(
            estate=self.estate,
            access_event=self.access_event,
            rule_code=SecurityAlert.RuleCode.UNKNOWN_VEHICLE,
            severity=SecurityAlert.Severity.HIGH,
            title="Unknown vehicle detected",
            description="Vehicle registration was not recognized.",
            detected_registration="KCA123A",
        )

        self.assign_url = reverse(
            "security-alert-assign",
            kwargs={"pk": self.alert.pk},
        )

    def test_estate_admin_can_assign_to_estate_security(self):
        self.api_client.force_authenticate(user=self.estate_admin)

        response = cast(
            HttpResponseBase,
            self.api_client.post(
                self.assign_url,
                {"assigned_to": str(self.security.pk)},
                format="json",
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.assigned_to,
            self.security,
        )

    def test_estate_admin_cannot_assign_to_outsider(self):
        self.api_client.force_authenticate(user=self.estate_admin)

        response = cast(
            HttpResponseBase,
            self.api_client.post(
                self.assign_url,
                {"assigned_to": str(self.outsider.pk)},
                format="json",
            ),
        )

        self.assertEqual(response.status_code, 400)

        self.alert.refresh_from_db()

        self.assertIsNone(self.alert.assigned_to)

    def test_platform_admin_can_assign_to_active_non_member(self):
        platform_admin = User.objects.create_superuser(        # type: ignore
            email="platform@test.com",
            password="test-password",
        )

        active_non_member = User.objects.create_user(          # type: ignore
            email="active-user@test.com",
            password="test-password",
            role="RESIDENT",
        )

        self.api_client.force_authenticate(user=platform_admin)

        response = cast(
            HttpResponseBase,
            self.api_client.post(
                self.assign_url,
                {"assigned_to": str(active_non_member.pk)},
                format="json",
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.assigned_to,
            active_non_member,
        )

    def test_platform_admin_cannot_assign_to_inactive_user(self):
        platform_admin = User.objects.create_superuser(           # type: ignore
            email="platform2@test.com",
            password="test-password",
        )

        inactive_user = User.objects.create_user(           # type: ignore
            email="inactive@test.com",
            password="test-password",
            is_active=False,
        )

        self.api_client.force_authenticate(user=platform_admin)

        response = cast(
            HttpResponseBase,
            self.api_client.post(
                self.assign_url,
                {"assigned_to": str(inactive_user.pk)},
                format="json",
            ),
        )

        self.assertEqual(response.status_code, 400)

        self.alert.refresh_from_db()

        self.assertIsNone(self.alert.assigned_to)

    def test_platform_admin_cannot_assign_to_nonexistent_user(self):
        platform_admin = User.objects.create_superuser(           # type: ignore
            email="platform3@test.com",
            password="test-password",
        )

        nonexistent_user_id = uuid.uuid4()

        self.api_client.force_authenticate(user=platform_admin)

        response = cast(
            HttpResponseBase,
            self.api_client.post(
                self.assign_url,
                {"assigned_to": str(nonexistent_user_id)},
                format="json",
            ),
        )

        self.assertEqual(response.status_code, 400)

        self.alert.refresh_from_db()

        self.assertIsNone(self.alert.assigned_to)
