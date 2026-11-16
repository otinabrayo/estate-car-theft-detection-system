from django.db import transaction
from django.db.models import Q

from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from apps.estates.models import EstateMembership
from apps.estates.permissions import (
    is_platform_admin,
    is_estate_admin,
)

from .models import Resident
from .serializers import ResidentSerializer


class ResidentViewSet(viewsets.ModelViewSet):
    serializer_class = ResidentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        queryset = Resident.objects.select_related(
            "user",
            "apartment",
            "apartment__block",
            "apartment__block__estate",
        )

        if is_platform_admin(user):
            return queryset

        return queryset.filter(
            Q(user=user)
            | Q(
                apartment__block__estate__memberships__user=user,
                apartment__block__estate__memberships__role=(
                    EstateMembership.Role.ESTATE_ADMIN
                ),
                apartment__block__estate__memberships__is_active=True,
            )
        ).distinct()

    def perform_create(self, serializer):
        apartment = serializer.validated_data["apartment"]
        estate = apartment.block.estate

        if not is_estate_admin(self.request.user, estate):
            raise PermissionDenied(
                "Only estate administrators can register residents."
            )

        with transaction.atomic():
            resident = serializer.save()

            # Create an inactive resident membership if one does not exist.
            # Estate administrators can activate it after verification.
            EstateMembership.objects.get_or_create(
                estate=estate,
                user=resident.user,
                defaults={
                    "role": EstateMembership.Role.RESIDENT,
                    "is_active": False,
                },
            )

    def perform_update(self, serializer):
        if not is_platform_admin(self.request.user):
            if not is_estate_admin(
                self.request.user,
                self.get_object().apartment.block.estate
            ):
                raise PermissionDenied(
                    "Only estate administrators can update residents."
                )

        serializer.save()

    def perform_destroy(self, instance):
        if not is_platform_admin(self.request.user):
            if not is_estate_admin(
                self.request.user,
                instance.apartment.block.estate
            ):
                raise PermissionDenied(
                    "Only estate administrators can remove residents."
                )

        instance.delete()
