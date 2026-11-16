from django.contrib import admin

from .models import GateAccessEvent, VehicleMovementSession

@admin.register(VehicleMovementSession)
class VehicleMovementSessionAdmin(admin.ModelAdmin):
    list_display = (
        "vehicle_registration",
        "estate",
        "entry_gate",
        "entry_at",
        "exit_gate",
        "exit_at",
        "status",
    )

    list_filter = (
        "estate",
        "status",
        "entry_gate",
        "entry_at",
    )

    search_fields = ("vehicle_registration",)

    readonly_fields = (
        "id",
        "estate",
        "vehicle",
        "visitor_pass",
        "vehicle_registration",
        "entry_gate",
        "exit_gate",
        "entry_at",
        "exit_at",
        "status",
        "entry_recorded_by",
        "exit_recorded_by",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(GateAccessEvent)
class GateAccessEventAdmin(admin.ModelAdmin):
    list_display = (
        "direction",
        "detected_registration",
        "gate",
        "decision",
        "reason",
        "occurred_at",
    )

    list_filter = (
        "estate",
        "direction",
        "decision",
        "source",
    )

    search_fields = (
        "detected_registration",
        "reason",
    )

    readonly_fields = (
        "id",
        "idempotency_key",
        "estate",
        "gate",
        "movement_session",
        "vehicle",
        "visitor_pass",
        "direction",
        "decision",
        "detected_registration",
        "confidence",
        "reason",
        "source",
        "evidence_object_key",
        "metadata",
        "recorded_by",
        "occurred_at",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    