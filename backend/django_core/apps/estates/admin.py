from django.contrib import admin

from .models import (
    Estate,
    EstateMembership,
    ApartmentBlock,
    Apartment,
    Gate,
)


@admin.register(Estate)
class EstateAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "city",
        "county",
        "country",
        "is_active",
    )

    search_fields = ("name", "city", "county")
    list_filter = ("is_active", "county", "country")


@admin.register(EstateMembership)
class EstateMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "estate",
        "role",
        "is_active",
    )

    list_filter = ("role", "is_active", "estate")
    search_fields = ("user__email", "estate__name")


@admin.register(ApartmentBlock)
class ApartmentBlockAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "estate",
        "number_of_floors",
        "is_active",
    )

    list_filter = ("estate", "is_active")
    search_fields = ("name", "estate__name")


@admin.register(Apartment)
class ApartmentAdmin(admin.ModelAdmin):
    list_display = (
        "unit_number",
        "block",
        "floor_number",
        "bedrooms",
        "is_active",
    )

    list_filter = ("block__estate", "is_active")
    search_fields = ("unit_number", "block__name")


@admin.register(Gate)
class GateAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "estate",
        "gate_type",
        "is_active",
    )

    list_filter = ("estate", "gate_type", "is_active")
    search_fields = ("name", "code", "estate__name")
