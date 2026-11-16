from django.contrib import admin
from django.utils import timezone

from .models import Visitor, VisitorPass


@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "phone_number",
        "estate",
        "created_at",
    )
    list_filter = ("estate", "identification_type")
    search_fields = (
        "full_name",
        "phone_number",
        "email",
    )
    readonly_fields = ("id", "created_at", "updated_at")


@admin.action(description="Approve selected visitor passes")
def approve_passes(modeladmin, request, queryset):
    queryset.filter(
        status=VisitorPass.Status.PENDING,
        valid_until__gt=timezone.now(),
    ).update(
        status=VisitorPass.Status.APPROVED,
        approved_by=request.user,
        approved_at=timezone.now(),
    )


@admin.action(description="Revoke selected visitor passes")
def revoke_passes(modeladmin, request, queryset):
    queryset.filter(
        status__in=[
            VisitorPass.Status.PENDING,
            VisitorPass.Status.APPROVED,
        ],
    ).update(
        status=VisitorPass.Status.REVOKED,
        revoked_at=timezone.now(),
    )


@admin.register(VisitorPass)
class VisitorPassAdmin(admin.ModelAdmin):
    list_display = (
        "pass_code",
        "visitor",
        "host",
        "estate",
        "status",
        "valid_from",
        "valid_until",
        "entries_used",
        "max_entries",
    )
    list_filter = ("estate", "status")
    search_fields = (
        "pass_code",
        "visitor__full_name",
        "visitor__phone_number",
        "host__user__email",
    )
    readonly_fields = (
        "id",
        "pass_code",
        "entries_used",
        "approved_at",
        "revoked_at",
        "created_at",
        "updated_at",
    )
    actions = [approve_passes, revoke_passes]
