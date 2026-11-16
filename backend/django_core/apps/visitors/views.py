from django.db.models import Q
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.estates.models import EstateMembership
from apps.estates.permissions import is_platform_admin
from apps.residents.models import Resident

from .models import Visitor, VisitorPass
from .serializers import VisitorSerializer, VisitorPassSerializer


class VisitorViewSet(viewsets.ModelViewSet):
    serializer_class = VisitorSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        if is_platform_admin(user):
            return Visitor.objects.select_related("estate")

        staff_estates = EstateMembership.objects.filter(
            user=user,
            is_active=True,
            role__in=["ESTATE_ADMIN", "SECURITY"],
        ).values_list("estate_id", flat=True)

        hosted_visitor_ids = VisitorPass.objects.filter(
            host__user=user
        ).values_list("visitor_id", flat=True)

        return Visitor.objects.filter(
            Q(estate_id__in=staff_estates)
            | Q(id__in=hosted_visitor_ids)
        ).select_related("estate").distinct()

    def perform_update(self, serializer):
        visitor = self.get_object()
        user = self.request.user

        allowed = (
            is_platform_admin(user)
            or EstateMembership.objects.filter(
                user=user,
                estate=visitor.estate,
                is_active=True,
                role="ESTATE_ADMIN",
            ).exists()
        )

        if not allowed:
            raise PermissionDenied(
                "Only estate administrators can update visitor records."
            )

        serializer.save()

    def perform_destroy(self, instance):
        raise ValidationError(
            "Visitor records cannot be deleted because they may be "
            "linked to access history. Keep the record for audit purposes."
        )


class VisitorPassViewSet(viewsets.ModelViewSet):
    serializer_class = VisitorPassSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        queryset = VisitorPass.objects.select_related(
            "estate",
            "visitor",
            "host",
            "host__user",
            "host__apartment",
            "host__apartment__block",
        )

        if is_platform_admin(user):
            return queryset

        staff_estates = EstateMembership.objects.filter(
            user=user,
            is_active=True,
            role__in=["ESTATE_ADMIN", "SECURITY"],
        ).values_list("estate_id", flat=True)

        return queryset.filter(
            Q(estate_id__in=staff_estates)
            | Q(host__user=user)
        ).distinct()

    def perform_create(self, serializer):
        user = self.request.user
        host = serializer.validated_data["host"]

        visitor_pass = serializer.save(created_by=user)

        # A resident creating a pass for their own visitor is the
        # host's authorization. Staff-created passes require approval.
        if host.user_id == user.id:
            visitor_pass.status = VisitorPass.Status.APPROVED
            visitor_pass.approved_by = user
            visitor_pass.approved_at = timezone.now()
            visitor_pass.save(update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "updated_at",
            ])

    def update(self, request, *args, **kwargs):
        raise ValidationError(
            "Visitor passes cannot be edited. Revoke the pass and create a new one."
        )

    def partial_update(self, request, *args, **kwargs):
        raise ValidationError(
            "Visitor passes cannot be edited. Revoke the pass and create a new one."
        )

    def destroy(self, request, *args, **kwargs):
        raise ValidationError(
            "Visitor passes cannot be deleted because they are access records."
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        visitor_pass = self.get_object()
        user = request.user

        is_host = visitor_pass.host.user_id == user.id

        is_estate_admin = (
            is_platform_admin(user)
            or EstateMembership.objects.filter(
                user=user,
                estate=visitor_pass.estate,
                is_active=True,
                role="ESTATE_ADMIN",
            ).exists()
        )

        if not (is_host or is_estate_admin):
            raise PermissionDenied(
                "Only the host or an estate administrator can approve this pass."
            )

        if visitor_pass.status != VisitorPass.Status.PENDING:
            raise ValidationError(
                "Only pending passes can be approved."
            )

        if visitor_pass.valid_until <= timezone.now():
            visitor_pass.status = VisitorPass.Status.EXPIRED
            visitor_pass.save(update_fields=["status", "updated_at"])

            raise ValidationError("This visitor pass has already expired.")

        visitor_pass.status = VisitorPass.Status.APPROVED
        visitor_pass.approved_by = user
        visitor_pass.approved_at = timezone.now()

        visitor_pass.save(update_fields=[
            "status",
            "approved_by",
            "approved_at",
            "updated_at",
        ])

        return Response(
            self.get_serializer(visitor_pass).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        visitor_pass = self.get_object()
        user = request.user

        is_host = visitor_pass.host.user_id == user.id
        is_admin = (
            is_platform_admin(user)
            or EstateMembership.objects.filter(
                user=user,
                estate=visitor_pass.estate,
                is_active=True,
                role="ESTATE_ADMIN",
            ).exists()
        )

        if not (is_host or is_admin):
            raise PermissionDenied(
                "Only the host or an estate administrator can reject this pass."
            )

        if visitor_pass.status != VisitorPass.Status.PENDING:
            raise ValidationError("Only pending passes can be rejected.")

        visitor_pass.status = VisitorPass.Status.REJECTED
        visitor_pass.save(update_fields=["status", "updated_at"])

        return Response(self.get_serializer(visitor_pass).data)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        visitor_pass = self.get_object()
        user = request.user

        is_host = visitor_pass.host.user_id == user.id

        is_staff = (
            is_platform_admin(user)
            or EstateMembership.objects.filter(
                user=user,
                estate=visitor_pass.estate,
                is_active=True,
                role__in=["ESTATE_ADMIN", "SECURITY"],
            ).exists()
        )

        if not (is_host or is_staff):
            raise PermissionDenied(
                "You are not allowed to revoke this pass."
            )

        if visitor_pass.status not in [
            VisitorPass.Status.PENDING,
            VisitorPass.Status.APPROVED,
        ]:
            raise ValidationError(
                "Only pending or approved passes can be revoked."
            )

        visitor_pass.status = VisitorPass.Status.REVOKED
        visitor_pass.revoked_at = timezone.now()

        visitor_pass.save(update_fields=[
            "status",
            "revoked_at",
            "updated_at",
        ])

        return Response(self.get_serializer(visitor_pass).data)
