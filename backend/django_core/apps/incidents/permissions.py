from apps.estates.models import EstateMembership
from apps.estates.permissions import is_platform_admin

def can_manage_incidents(user, estate):
    if not user or not user.is_authenticated:
        return False

    if is_platform_admin(user):
        return True

    return EstateMembership.objects.filter(
        user=user,
        estate=estate,
        is_active=True,
        role__in=[
            EstateMembership.Role.ESTATE_ADMIN,
            EstateMembership.Role.SECURITY,
        ],
    ).exists()
