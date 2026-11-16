from django.db.models import Q

from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from apps.estates.models import EstateMembership
from apps.estates.permissions import (
    is_platform_admin,
    is_estate_admin,
)

from .models import Vehicle, AuthorizedDriver
from .serializers import (
    VehicleSerializer,
    AuthorizedDriverSerializer,
)


class VehicleViewSet(viewsets.ModelViewSet):
    serializer_class = VehicleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        queryset = Vehicle.objects.select_related(
            "estate",
            "registered_by",
            "registered_by__user",
            "registered_by__apartment",
        )

        if is_platform_admin(user):
            return queryset

        return queryset.filter(
            Q(
                estate__memberships__user=user,
                estate__memberships__is_active=True,
                estate__memberships__role__in=[
                    EstateMembership.Role.ESTATE_ADMIN,
                    EstateMembership.Role.SECURITY,
                ],
            )
            | Q(registered_by__user=user)
        ).distinct()

    def perform_create(self, serializer):
        estate = serializer.validated_data["estate"]

        if not is_estate_admin(self.request.user, estate):
            raise PermissionDenied(
                "Only estate administrators can register vehicles."
            )

        serializer.save()

    def perform_update(self, serializer):
        vehicle = self.get_object()

        if not is_platform_admin(self.request.user):
            if not is_estate_admin(self.request.user, vehicle.estate):
                raise PermissionDenied(
                    "Only estate administrators can update vehicles."
                )

        serializer.save()

    def perform_destroy(self, instance):
        if not is_platform_admin(self.request.user):
            if not is_estate_admin(self.request.user, instance.estate):
                raise PermissionDenied(
                    "Only estate administrators can remove vehicles."
                )

        instance.delete()


class AuthorizedDriverViewSet(viewsets.ModelViewSet):
    serializer_class = AuthorizedDriverSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        queryset = AuthorizedDriver.objects.select_related(
            "vehicle",
            "vehicle__estate",
            "vehicle__registered_by",
            "resident",
        )

        if is_platform_admin(user):
            return queryset

        return queryset.filter(
            Q(
                vehicle__estate__memberships__user=user,
                vehicle__estate__memberships__is_active=True,
                vehicle__estate__memberships__role__in=[
                    EstateMembership.Role.ESTATE_ADMIN,
                    EstateMembership.Role.SECURITY,
                ],
            )
            | Q(vehicle__registered_by__user=user)
        ).distinct()

    def perform_create(self, serializer):
        vehicle = serializer.validated_data["vehicle"]

        if not is_estate_admin(self.request.user, vehicle.estate):
            raise PermissionDenied(
                "Only estate administrators can authorize drivers."
            )

        serializer.save(authorized_by=self.request.user)

    def perform_update(self, serializer):
        driver = self.get_object()

        if not is_platform_admin(self.request.user):
            if not is_estate_admin(
                self.request.user,
                driver.vehicle.estate
            ):
                raise PermissionDenied(
                    "Only estate administrators can update authorizations."
                )

        serializer.save()

    def perform_destroy(self, instance):
        if not is_platform_admin(self.request.user):
            if not is_estate_admin(
                self.request.user,
                instance.vehicle.estate
            ):
                raise PermissionDenied(
                    "Only estate administrators can remove authorizations."
                )

        instance.delete()
