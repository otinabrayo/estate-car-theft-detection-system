from rest_framework import serializers

from .models import Resident


class ResidentSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(
        source="user.email",
        read_only=True
    )

    apartment_label = serializers.StringRelatedField(
        source="apartment",
        read_only=True
    )

    estate_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Resident
        fields = [
            "id",
            "user",
            "user_email",
            "apartment",
            "apartment_label",
            "estate_id",
            "relationship",
            "status",
            "move_in_date",
            "move_out_date",
            "is_primary_contact",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        move_in = attrs.get(
            "move_in_date",
            getattr(self.instance, "move_in_date", None)
        )

        move_out = attrs.get(
            "move_out_date",
            getattr(self.instance, "move_out_date", None)
        )

        if move_out and move_in and move_out < move_in:
            raise serializers.ValidationError(
                "Move-out date cannot precede move-in date."
            )

        return attrs
