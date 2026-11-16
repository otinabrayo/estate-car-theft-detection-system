from rest_framework import serializers

from .models import (
    Estate,
    ApartmentBlock,
    Apartment,
    Gate,
)


class EstateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Estate
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at")


class ApartmentBlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApartmentBlock
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at")


class ApartmentSerializer(serializers.ModelSerializer):
    estate = serializers.UUIDField(
        source="block.estate_id",
        read_only=True
    )

    class Meta:
        model = Apartment
        fields = (
            "id",
            "block",
            "estate",
            "unit_number",
            "floor_number",
            "bedrooms",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "estate",
            "created_at",
            "updated_at",
        )


class GateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Gate
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at")
