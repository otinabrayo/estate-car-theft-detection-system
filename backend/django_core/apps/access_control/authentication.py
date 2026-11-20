import secrets

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class InternalServicePrincipal:
    """
    Represents an authenticated internal service rather than a human user.
    """

    is_authenticated = True
    is_anonymous = False

    def __str__(self):
        return "internal-service"


class InternalServiceTokenAuthentication(BaseAuthentication):

    def authenticate(self, request):
        supplied_token = request.headers.get(
            "X-Internal-Service-Token"
        )

        if not supplied_token:
            return None

        expected_token = getattr(
            settings,
            "DJANGO_INTERNAL_SERVICE_TOKEN",
            "",
        )

        if not expected_token:
            raise AuthenticationFailed(
                "Internal service authentication is not configured."
            )

        if not secrets.compare_digest(
            supplied_token,
            expected_token,
        ):
            raise AuthenticationFailed(
                "Invalid internal service token."
            )

        return InternalServicePrincipal(), "internal-service"

    def authenticate_header(self, request) -> None:
        return None
