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


class SecurityAlertLifecycleTests(TestCase):

    def setUp(self):
        self.api_client = APIClient()

        self.estate = Estate.objects.create(
            name="Lifecycle Estate",
            address="Nairobi",
            city="Nairobi",
            county="Nairobi",
            country="Kenya",
        )

        self.other_estate = Estate.objects.create(
            name="Other Estate",
            address="Mombasa",
            city="Mombasa",
            county="Mombasa",
            country="Kenya",
        )

        self.gate = Gate.objects.create(
            estate=self.estate,
            name="Main Gate",
            code="MAIN",
        )

        self.estate_admin = User.objects.create_user(  # type: ignore
            email="lifecycle-admin@test.com",
            password="test-password",
            role="ESTATE_ADMIN",
        )

        self.security = User.objects.create_user(  # type: ignore
            email="lifecycle-security@test.com",
            password="test-password",
            role="SECURITY",
        )

        self.outsider = User.objects.create_user(  # type: ignore
            email="lifecycle-outsider@test.com",
            password="test-password",
            role="SECURITY",
        )

        self.resident = User.objects.create_user(  # type: ignore
            email="lifecycle-resident@test.com",
            password="test-password",
            role="RESIDENT",
        )

        self.platform_admin = User.objects.create_superuser(  # type: ignore
            email="lifecycle-platform@test.com",
            password="test-password",
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

        EstateMembership.objects.create(
            estate=self.estate,
            user=self.resident,
            role=EstateMembership.Role.RESIDENT,
            is_active=True,
        )

        EstateMembership.objects.create(
            estate=self.other_estate,
            user=self.outsider,
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

    def action_url(self, action):
        return reverse(
            f"security-alert-{action}",
            kwargs={"pk": self.alert.pk},
        )

    def post_action(self, action, user, data=None):
        self.api_client.force_authenticate(user=user)

        return cast(
            HttpResponseBase,
            self.api_client.post(
                self.action_url(action),
                data or {},
                format="json",
            ),
        )


    # --------------------------------------------------
    # ACKNOWLEDGEMENT
    # --------------------------------------------------

    def test_security_can_acknowledge_open_alert(self):
        response = self.post_action(
            "acknowledge",
            self.security,
        )

        self.assertEqual(response.status_code, 200)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.ACKNOWLEDGED,
        )
        self.assertEqual(self.alert.acknowledged_by, self.security)
        self.assertIsNotNone(self.alert.acknowledged_at)

    def test_estate_admin_can_acknowledge_open_alert(self):
        response = self.post_action(
            "acknowledge",
            self.estate_admin,
        )

        self.assertEqual(response.status_code, 200)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.ACKNOWLEDGED,
        )

    def test_cannot_acknowledge_already_acknowledged_alert(self):
        self.alert.status = SecurityAlert.Status.ACKNOWLEDGED
        self.alert.save()

        response = self.post_action(
            "acknowledge",
            self.security,
        )

        self.assertEqual(response.status_code, 400)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.ACKNOWLEDGED,
        )

    # --------------------------------------------------
    # INVESTIGATION
    # --------------------------------------------------

    def test_security_can_investigate_open_alert(self):
        response = self.post_action(
            "investigate",
            self.security,
        )

        self.assertEqual(response.status_code, 200)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.INVESTIGATING,
        )

        self.assertEqual(
            self.alert.acknowledged_by,
            self.security,
        )

        self.assertIsNotNone(self.alert.acknowledged_at)

    def test_security_can_investigate_acknowledged_alert(self):
        self.alert.status = SecurityAlert.Status.ACKNOWLEDGED
        self.alert.acknowledged_by = self.estate_admin
        self.alert.save()

        response = self.post_action(
            "investigate",
            self.security,
        )

        self.assertEqual(response.status_code, 200)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.INVESTIGATING,
        )

        self.assertEqual(
            self.alert.acknowledged_by,
            self.estate_admin,
        )

    def test_cannot_investigate_resolved_alert(self):
        self.alert.status = SecurityAlert.Status.RESOLVED
        self.alert.save()

        response = self.post_action(
            "investigate",
            self.security,
        )

        self.assertEqual(response.status_code, 400)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.RESOLVED,
        )

    # --------------------------------------------------
    # RESOLUTION
    # --------------------------------------------------

    def test_security_can_resolve_acknowledged_alert(self):
        self.alert.status = SecurityAlert.Status.ACKNOWLEDGED
        self.alert.save()

        response = self.post_action(
            "resolve",
            self.security,
            {
                "resolution_notes": "Vehicle identity verified.",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.RESOLVED,
        )
        self.assertEqual(self.alert.resolved_by, self.security)
        self.assertEqual(
            self.alert.resolution_notes,
            "Vehicle identity verified.",
        )
        self.assertIsNotNone(self.alert.resolved_at)

    def test_cannot_resolve_open_alert(self):
        response = self.post_action(
            "resolve",
            self.security,
            {
                "resolution_notes": "Vehicle identity verified.",
            },
        )

        self.assertEqual(response.status_code, 400)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.OPEN,
        )
        self.assertIsNone(self.alert.resolved_by)

    def test_cannot_resolve_without_valid_notes(self):
        self.alert.status = SecurityAlert.Status.ACKNOWLEDGED
        self.alert.save()

        response = self.post_action(
            "resolve",
            self.security,
            {
                "resolution_notes": "OK",
            },
        )

        self.assertEqual(response.status_code, 400)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.ACKNOWLEDGED,
        )

    # --------------------------------------------------
    # DISMISSAL
    # --------------------------------------------------

    def test_security_can_dismiss_open_alert(self):
        response = self.post_action(
            "dismiss",
            self.security,
            {
                "dismissal_reason": "False positive confirmed.",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.DISMISSED,
        )
        self.assertEqual(self.alert.dismissed_by, self.security)
        self.assertEqual(
            self.alert.dismissal_reason,
            "False positive confirmed.",
        )
        self.assertIsNotNone(self.alert.dismissed_at)

    def test_cannot_dismiss_resolved_alert(self):
        self.alert.status = SecurityAlert.Status.RESOLVED
        self.alert.save()

        response = self.post_action(
            "dismiss",
            self.security,
            {
                "dismissal_reason": "False positive confirmed.",
            },
        )

        self.assertEqual(response.status_code, 400)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.RESOLVED,
        )

    def test_cannot_dismiss_without_valid_reason(self):
        response = self.post_action(
            "dismiss",
            self.security,
            {
                "dismissal_reason": "No",
            },
        )

        self.assertEqual(response.status_code, 400)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.OPEN,
        )

    # --------------------------------------------------
    # AUTHORIZATION AND ESTATE ISOLATION
    # --------------------------------------------------

    def test_platform_admin_can_acknowledge_alert(self):
        response = self.post_action(
            "acknowledge",
            self.platform_admin,
        )

        self.assertEqual(response.status_code, 200)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.ACKNOWLEDGED,
        )

    def test_outsider_cannot_access_alert(self):
        response = self.post_action(
            "acknowledge",
            self.outsider,
        )

        self.assertEqual(response.status_code, 404)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.OPEN,
        )

    def test_resident_cannot_manage_alert(self):
        response = self.post_action(
            "acknowledge",
            self.resident,
        )

        self.assertEqual(response.status_code, 404)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.OPEN,
        )

    def test_inactive_security_membership_cannot_manage_alert(self):
        membership = EstateMembership.objects.get(
            estate=self.estate,
            user=self.security,
        )

        membership.is_active = False
        membership.save(update_fields=["is_active"])

        response = self.post_action(
            "acknowledge",
            self.security,
        )

        self.assertEqual(response.status_code, 404)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.OPEN,
        )

    def test_unauthenticated_user_cannot_manage_alert(self):
        self.api_client.force_authenticate(user=None)

        response = cast(
            HttpResponseBase,
            self.api_client.post(
                self.action_url("acknowledge"),
                {},
                format="json",
            ),
        )

        self.assertEqual(response.status_code, 401)

        self.alert.refresh_from_db()

        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.OPEN,
        )

    def test_inactive_estate_admin_cannot_manage_alert(self):
        membership = EstateMembership.objects.get(
            estate=self.estate,
            user=self.estate_admin,
        )

        membership.is_active = False
        membership.save(update_fields=["is_active"])

        response = self.post_action(
            "acknowledge",
            self.estate_admin,
        )

        self.assertEqual(response.status_code, 404)

        self.alert.refresh_from_db()
        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.OPEN,
        )

    def test_super_admin_role_without_superuser_flag_can_manage_alert(self):
        super_admin = User.objects.create_user(  # type: ignore
            email="role-superadmin@test.com",
            password="test-password",
            role="SUPER_ADMIN",
        )

        self.assertFalse(super_admin.is_superuser)

        response = self.post_action(
            "acknowledge",
            super_admin,
        )

        self.assertEqual(response.status_code, 200)

        self.alert.refresh_from_db()
        self.assertEqual(
            self.alert.status,
            SecurityAlert.Status.ACKNOWLEDGED,
        )

    def test_resolved_alert_cannot_be_reopened(self):
        self.alert.status = SecurityAlert.Status.RESOLVED
        self.alert.save()

        actions = [
            "acknowledge",
            "investigate",
            "resolve",
            "dismiss",
        ]

        for action in actions:
            with self.subTest(action=action):
                response = self.post_action(
                    action,
                    self.security,
                    {
                        "resolution_notes": "Previously resolved.",
                        "dismissal_reason": "Previously resolved.",
                    },
                )

                self.assertEqual(response.status_code, 400)

                self.alert.refresh_from_db()
                self.assertEqual(
                    self.alert.status,
                    SecurityAlert.Status.RESOLVED,
                )

    def test_dismissed_alert_cannot_be_reopened(self):
        self.alert.status = SecurityAlert.Status.DISMISSED
        self.alert.save()

        actions = [
            "acknowledge",
            "investigate",
            "resolve",
            "dismiss",
        ]

        for action in actions:
            with self.subTest(action=action):
                response = self.post_action(
                    action,
                    self.security,
                    {
                        "resolution_notes": "Previously dismissed.",
                        "dismissal_reason": "Previously dismissed.",
                    },
                )

                self.assertEqual(response.status_code, 400)

                self.alert.refresh_from_db()
                self.assertEqual(
                    self.alert.status,
                    SecurityAlert.Status.DISMISSED,
                )
                