from django.contrib import admin
from django.utils import timezone

from .models import Vehicle, AuthorizedDriver


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = (
        "registration_number",
        "make",
        "model",
        "estate",
        "status",
        "is_active",
    )

    list_filter = (
        "status",
        "vehicle_type",
        "estate",
        "is_active",
    )

    search_fields = (
        "registration_number",
        "normalized_registration",
        "make",
        "model",
    )

    readonly_fields = (
        "id",
        "normalized_registration",
        "approved_at",
        "created_at",
        "updated_at",
    )

    actions = ("approve_vehicles", "reject_vehicles")

    @admin.action(description="Approve selected vehicles")
    def approve_vehicles(self, request, queryset):
        queryset.update(
            status=Vehicle.Status.APPROVED,
            approved_by=request.user,
            approved_at=timezone.now(),
        )

    @admin.action(description="Reject selected vehicles")
    def reject_vehicles(self, request, queryset):
        queryset.update(
            status=Vehicle.Status.REJECTED,
            approved_by=request.user,
        )


@admin.register(AuthorizedDriver)
class AuthorizedDriverAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "vehicle",
        "phone_number",
        "status",
        "valid_from",
        "valid_until",
    )

    list_filter = ("status",)

    search_fields = (
        "full_name",
        "phone_number",
        "vehicle__registration_number",
    )

    readonly_fields = ("id", "created_at", "updated_at")

    actions = ("activate_drivers", "revoke_drivers")

    @admin.action(description="Activate selected driver authorizations")
    def activate_drivers(self, request, queryset):
        queryset.update(status=AuthorizedDriver.Status.ACTIVE)

    @admin.action(description="Revoke selected driver authorizations")
    def revoke_drivers(self, request, queryset):
        queryset.update(status=AuthorizedDriver.Status.REVOKED)
        