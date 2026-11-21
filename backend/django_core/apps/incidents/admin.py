from django.contrib import admin

from .models import Incident, IncidentActivity, IncidentAlert


class IncidentAlertInline(admin.TabularInline):
    model = IncidentAlert
    extra = 0
    readonly_fields = ("created_at",)


class IncidentActivityInline(admin.TabularInline):
    model = IncidentActivity
    extra = 0
    can_delete = False
    readonly_fields = (
        "actor",
        "action",
        "description",
        "metadata",
        "created_at",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "title",
        "estate",
        "incident_type",
        "severity",
        "status",
        "assigned_to",
        "created_at",
    )

    list_filter = (
        "incident_type",
        "severity",
        "status",
        "estate",
    )

    search_fields = (
        "reference",
        "title",
        "description",
    )

    readonly_fields = (
        "reference",
        "created_at",
        "updated_at",
    )

    inlines = [
        IncidentAlertInline,
        IncidentActivityInline,
    ]


@admin.register(IncidentAlert)
class IncidentAlertAdmin(admin.ModelAdmin):
    list_display = (
        "incident",
        "alert",
        "linked_by",
        "created_at",
    )

    readonly_fields = ("created_at",)


@admin.register(IncidentActivity)
class IncidentActivityAdmin(admin.ModelAdmin):
    list_display = (
        "incident",
        "actor",
        "action",
        "created_at",
    )

    list_filter = ("action",)
    readonly_fields = (
        "incident",
        "actor",
        "action",
        "description",
        "metadata",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
