from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from .models import (
    Estate,
    ApartmentBlock,
    Apartment,
    Gate,
)

from .serializers import (
    EstateSerializer,
    ApartmentBlockSerializer,
    ApartmentSerializer,
    GateSerializer,
)

from .permissions import (
    EstateAdminOrReadOnly,
    is_platform_admin,
    is_estate_admin,
)


class EstateViewSet(viewsets.ModelViewSet):
    serializer_class = EstateSerializer
    permission_classes = [IsAuthenticated, EstateAdminOrReadOnly]

    def get_queryset(self):
        user = self.request.user

        if is_platform_admin(user):
            return Estate.objects.all()

        return Estate.objects.filter(
            memberships__user=user,
            memberships__is_active=True,
        ).distinct()

    def perform_create(self, serializer):
        if not is_platform_admin(self.request.user):
            raise PermissionDenied(
                "Only platform administrators can create estates."
            )

        serializer.save()


class ApartmentBlockViewSet(viewsets.ModelViewSet):
    serializer_class = ApartmentBlockSerializer
    permission_classes = [IsAuthenticated, EstateAdminOrReadOnly]

    def get_queryset(self):
        user = self.request.user

        queryset = ApartmentBlock.objects.select_related("estate")

        if is_platform_admin(user):
            return queryset

        return queryset.filter(
            estate__memberships__user=user,
            estate__memberships__is_active=True,
        ).distinct()

    def perform_create(self, serializer):
        estate = serializer.validated_data["estate"]

        if not is_estate_admin(self.request.user, estate):
            raise PermissionDenied(
                "You must be an estate administrator to create blocks."
            )

        serializer.save()


class ApartmentViewSet(viewsets.ModelViewSet):
    serializer_class = ApartmentSerializer
    permission_classes = [IsAuthenticated, EstateAdminOrReadOnly]

    def get_queryset(self):
        user = self.request.user

        queryset = Apartment.objects.select_related(
            "block",
            "block__estate",
        )

        if is_platform_admin(user):
            return queryset

        return queryset.filter(
            block__estate__memberships__user=user,
            block__estate__memberships__is_active=True,
        ).distinct()

    def perform_create(self, serializer):
        block = serializer.validated_data["block"]

        if not is_estate_admin(self.request.user, block.estate):
            raise PermissionDenied(
                "You must be an estate administrator to create apartments."
            )

        serializer.save()


class GateViewSet(viewsets.ModelViewSet):
    serializer_class = GateSerializer
    permission_classes = [IsAuthenticated, EstateAdminOrReadOnly]

    def get_queryset(self):
        user = self.request.user

        queryset = Gate.objects.select_related("estate")

        if is_platform_admin(user):
            return queryset

        return queryset.filter(
            estate__memberships__user=user,
            estate__memberships__is_active=True,
        ).distinct()

    def perform_create(self, serializer):
        estate = serializer.validated_data["estate"]

        if not is_estate_admin(self.request.user, estate):
            raise PermissionDenied(
                "You must be an estate administrator to create gates."
            )

        serializer.save()
