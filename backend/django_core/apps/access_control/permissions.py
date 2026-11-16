from rest_framework.permissions import BasePermission

from apps.estates.models import EstateMembership
from apps.estates.permissions import is_platform_admin

class CanOperateGate(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        return is_platform_admin(request.user) or (
            EstateMembership.objects.filter(
                user=request.user,
                estate=obj.estate,
                is_active=True,
                role__in=["ESTATE_ADMIN", "SECURITY"],
            ).exists()
        )