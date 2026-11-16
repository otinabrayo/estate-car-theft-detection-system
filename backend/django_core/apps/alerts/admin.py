from django.contrib import admin

from .models import SecurityAlert


@admin.register(SecurityAlert)
class SecurityAlertAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "detected_registration",
        "rule_code",
        "severity",
        "status",
        "estate",
        "assigned_to",
        "created_at",
    )

    list_filter = (
        "estate",
        "severity",
        "status",
        "rule_code",
    )

    search_fields = (
        "title",
        "detected_registration",
        "description",
    )

    readonly_fields = (
        "id",
        "estate",
        "access_event",
        "movement_session",
        "rule_code",
        "severity",
        "title",
        "description",
        "detected_registration",
        "acknowledged_by",
        "acknowledged_at",
        "resolved_by",
        "resolved_at",
        "dismissed_by",
        "dismissed_at",
        "metadata",
        "created_at",
        "updated_at",
    )
    