from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.estates.models import Estate, EstateMembership
from apps.incidents.models import Incident, IncidentActivity


User = get_user_model()


class IncidentAPITests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(  # type: ignore
            email="security@example.com",
            password="TestPassword123!",
        )

        self.estate = Estate.objects.create(
            name="Green Estate",
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

        client = APIClient()
        client.force_authenticate(user=self.user)
        self.client = client

        self.incident_url = reverse("incident-list")

    def create_incident(self, **kwargs):
        defaults = {
            "estate": self.estate,
            "incident_type": Incident.IncidentType.THEFT_SUSPECTED,
            "severity": Incident.Severity.HIGH,
            "title": "Suspected vehicle theft",
            "description": "Vehicle exited without a matching entry.",
            "created_by": self.user,
        }
        defaults.update(kwargs)

        return Incident.objects.create(**defaults)

    def detail_url(self, incident, action=None):
        url = reverse(
            "incident-detail",
            kwargs={"pk": incident.pk},
        )

        if action:
            url += f"{action}/"

        return url

    # --------------------------------------------------
    # INCIDENT CREATION
    # --------------------------------------------------

    def test_security_member_can_create_incident(self):
        response = self.client.post(
            self.incident_url,
            {
                "estate": str(self.estate.id),
                "incident_type": "THEFT_SUSPECTED",
                "severity": "CRITICAL",
                "title": "Vehicle theft suspected",
                "description": "Suspicious vehicle movement detected.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        incident = Incident.objects.get(
            reference=response.json()["reference"]
        )

        self.assertEqual(incident.estate, self.estate)
        self.assertEqual(incident.created_by, self.user)
        self.assertEqual(incident.status, Incident.Status.OPEN)

        self.assertTrue(
            IncidentActivity.objects.filter(
                incident=incident,
                action=IncidentActivity.Action.CREATED,
            ).exists()
        )

    def test_user_without_estate_membership_cannot_create_incident(self):
        outsider = User.objects.create_user(   # type: ignore
            email="outsider@example.com",
            password="TestPassword123!",
        )

        client = APIClient()
        client.force_authenticate(user=outsider)

        response = client.post(
            self.incident_url,
            {
                "estate": str(self.estate.id),
                "incident_type": "THEFT_SUSPECTED",
                "severity": "HIGH",
                "title": "Unauthorized incident",
                "description": "This should not be created.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)  # type: ignore
        self.assertEqual(Incident.objects.count(), 0)

    # --------------------------------------------------
    # ESTATE ACCESS ISOLATION
    # --------------------------------------------------

    def test_user_can_only_list_incidents_from_accessible_estates(self):
        accessible_incident = self.create_incident()

        other_estate = Estate.objects.create(
            name="Other Estate",
            address="Mombasa",
            city="Mombasa",
            county="Mombasa",
        )

        inaccessible_incident = self.create_incident(
            estate=other_estate,
            title="Other estate incident",
        )

        response = self.client.get(self.incident_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = getattr(response, "data", response.json())
        returned_ids = {
            item["id"] for item in response_data["results"]
        } if isinstance(response_data, dict) else {
            item["id"] for item in response_data
        }

        self.assertIn(str(accessible_incident.id), returned_ids)
        self.assertNotIn(str(inaccessible_incident.id), returned_ids)

    def test_resident_cannot_retrieve_security_incident(self):
        resident = User.objects.create_user(   # type: ignore
            email="resident@example.com",
            password="TestPassword123!",
        )

        EstateMembership.objects.create(
            user=resident,
            estate=self.estate,
            role=EstateMembership.Role.RESIDENT,
            is_active=True,
        )

        incident = self.create_incident()

        self.client.force_authenticate(user=resident)  # type: ignore[attr-defined]

        response = self.client.get(
            self.detail_url(incident)
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --------------------------------------------------
    # INVESTIGATOR ASSIGNMENT
    # --------------------------------------------------

    def test_security_member_can_assign_investigator(self):
        investigator = User.objects.create_user( # type: ignore
            email="investigator@example.com",
            password="TestPassword123!",
        )

        EstateMembership.objects.create(
            user=investigator,
            estate=self.estate,
            role=EstateMembership.Role.SECURITY,
            is_active=True,
        )

        incident = self.create_incident()

        response = self.client.post(
            self.detail_url(incident, "assign"),
            {"user_id": str(investigator.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        incident.refresh_from_db()

        self.assertEqual(incident.assigned_to, investigator)

        self.assertTrue(
            IncidentActivity.objects.filter(
                incident=incident,
                action=IncidentActivity.Action.ASSIGNED,
            ).exists()
        )

    def test_cannot_assign_resident_as_investigator(self):
        resident = User.objects.create_user(      # type: ignore
            email="resident2@example.com",
            password="TestPassword123!",
        )

        EstateMembership.objects.create(
            user=resident,
            estate=self.estate,
            role=EstateMembership.Role.RESIDENT,
            is_active=True,
        )

        incident = self.create_incident()

        response = self.client.post(
            self.detail_url(incident, "assign"),
            {"user_id": str(resident.id)},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        incident.refresh_from_db()
        self.assertIsNone(incident.assigned_to)

    # --------------------------------------------------
    # INCIDENT STATUS TRANSITIONS
    # --------------------------------------------------

    def test_incident_can_move_into_investigation(self):
        incident = self.create_incident()

        response = self.client.post(
            self.detail_url(incident, "transition"),
            {"status": Incident.Status.INVESTIGATING},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        incident.refresh_from_db()

        self.assertEqual(
            incident.status,
            Incident.Status.INVESTIGATING,
        )

    def test_incident_cannot_skip_investigation_and_resolve(self):
        incident = self.create_incident()

        response = self.client.post(
            self.detail_url(incident, "transition"),
            {
                "status": Incident.Status.RESOLVED,
                "resolution_summary": "Vehicle recovered.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        incident.refresh_from_db()
        self.assertEqual(incident.status, Incident.Status.OPEN)

    def test_incident_requires_resolution_summary(self):
        incident = self.create_incident(
            status=Incident.Status.INVESTIGATING,
        )

        response = self.client.post(
            self.detail_url(incident, "transition"),
            {"status": Incident.Status.RESOLVED},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        incident.refresh_from_db()

        self.assertEqual(
            incident.status,
            Incident.Status.INVESTIGATING,
        )

    def test_incident_can_be_resolved_and_closed(self):
        incident = self.create_incident(
            status=Incident.Status.INVESTIGATING,
        )

        resolve_response = self.client.post(
            self.detail_url(incident, "transition"),
            {
                "status": Incident.Status.RESOLVED,
                "resolution_summary": "Vehicle recovered and verified.",
            },
            format="json",
        )

        self.assertEqual(
            resolve_response.status_code,
            status.HTTP_200_OK,
        )

        incident.refresh_from_db()

        self.assertEqual(incident.status, Incident.Status.RESOLVED)
        self.assertEqual(incident.resolved_by, self.user)
        self.assertIsNotNone(incident.resolved_at)

        close_response = self.client.post(
            self.detail_url(incident, "transition"),
            {"status": Incident.Status.CLOSED},
            format="json",
        )

        self.assertEqual(
            close_response.status_code,
            status.HTTP_200_OK,
        )

        incident.refresh_from_db()

        self.assertEqual(incident.status, Incident.Status.CLOSED)
        self.assertEqual(incident.closed_by, self.user)
        self.assertIsNotNone(incident.closed_at)

    def test_closed_incident_cannot_be_reopened(self):
        incident = self.create_incident(
            status=Incident.Status.CLOSED,
            resolved_by=self.user,
            resolved_at=timezone.now(),
            closed_by=self.user,
            closed_at=timezone.now(),
        )

        response = self.client.post(
            self.detail_url(incident, "transition"),
            {"status": Incident.Status.INVESTIGATING},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        incident.refresh_from_db()
        self.assertEqual(incident.status, Incident.Status.CLOSED)

    # --------------------------------------------------
    # INVESTIGATION ACTIVITY
    # --------------------------------------------------

    def test_security_member_can_add_investigation_note(self):
        incident = self.create_incident()

        response = self.client.post(
            self.detail_url(incident, "add_note"),
            {
                "description": "Reviewed gate footage. Vehicle registration recorded."
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        activity = IncidentActivity.objects.get(
            incident=incident,
            action=IncidentActivity.Action.NOTE_ADDED,
        )

        self.assertEqual(activity.actor, self.user)
        self.assertIn("Reviewed gate footage", activity.description)

    def test_empty_investigation_note_is_rejected(self):
        incident = self.create_incident()

        response = self.client.post(
            self.detail_url(incident, "add_note"),
            {"description": "   "},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertFalse(
            IncidentActivity.objects.filter(
                incident=incident,
                action=IncidentActivity.Action.NOTE_ADDED,
            ).exists()
        )
