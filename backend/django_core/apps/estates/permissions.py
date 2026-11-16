from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import EstateMembership


def is_platform_admin(user):
    return (
        user.is_authenticated
        and (
            user.is_superuser
            or user.role == "SUPER_ADMIN"
        )
    )


def has_estate_access(user, estate):
    if is_platform_admin(user):
        return True

    return EstateMembership.objects.filter(
        user=user,
        estate=estate,
        is_active=True,
    ).exists()


def is_estate_admin(user, estate):
    if is_platform_admin(user):
        return True

    return EstateMembership.objects.filter(
        user=user,
        estate=estate,
        role=EstateMembership.Role.ESTATE_ADMIN,
        is_active=True,
    ).exists()


class EstateAdminOrReadOnly(BasePermission):
    """
    Only estate administrators can modify estate resources.
    Active estate members can read them.
    """

    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        estate = getattr(obj, "estate", None)

        if estate is None and hasattr(obj, "block"):
            estate = obj.block.estate

        if estate is None:
            return False

        if request.method in SAFE_METHODS:
            return has_estate_access(request.user, estate)

        return is_estate_admin(request.user, estate)
