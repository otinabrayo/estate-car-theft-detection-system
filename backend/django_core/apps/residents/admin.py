from django.contrib import admin

from .models import Resident


@admin.register(Resident)
class ResidentAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "apartment",
        "relationship",
        "status",
        "is_primary_contact",
    )

    list_filter = (
        "status",
        "relationship",
        "is_primary_contact",
    )

    search_fields = (
        "user__email",
        "apartment__unit_number",
        "apartment__block__name",
    )

    readonly_fields = ("id", "created_at", "updated_at")
    