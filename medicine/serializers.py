"""Serializers for the global medicine catalog."""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Medicine


class PharmacyMedicineSerializer(serializers.ModelSerializer):
    """Public-facing catalog serializer shown to pharmacy users."""

    class Meta:
        model = Medicine
        fields = (
            'id',
            'generic_name',
            'brand_name',
            'strength',
            'dosage_form',
            'route',
            'manufacturer',
            'pack_size',
            'pack_size_unit',
            'description',
            'nafdac_registration',
        )
        read_only_fields = fields


class AdminMedicineSerializer(serializers.ModelSerializer):
    """Admin-facing serializer exposing provenance metadata."""

    creator_name = serializers.SerializerMethodField()
    creator_role = serializers.SerializerMethodField()
    creator_pharmacy = serializers.SerializerMethodField()

    class Meta:
        model = Medicine
        fields = (
            'id',
            'generic_name',
            'brand_name',
            'strength',
            'dosage_form',
            'route',
            'manufacturer',
            'pack_size',
            'pack_size_unit',
            'description',
            'nafdac_registration',
            'source',
            'verification_status',
            'created_by',
            'creator_name',
            'creator_role',
            'created_by_pharmacy',
            'creator_pharmacy',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields

    def get_creator_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.email
        return None

    def get_creator_role(self, obj):
        if obj.created_by:
            return obj.created_by.role
        return None

    def get_creator_pharmacy(self, obj):
        if obj.created_by_pharmacy:
            return obj.created_by_pharmacy.brand_name
        return None


class MedicineListSerializer(PharmacyMedicineSerializer):
    """Backward-compatible alias for catalog list responses."""

    class Meta(PharmacyMedicineSerializer.Meta):
        fields = (
            'id',
            'generic_name',
            'brand_name',
            'strength',
            'dosage_form',
            'route',
        )
        read_only_fields = fields


class MedicineDetailSerializer(AdminMedicineSerializer):
    """Backward-compatible alias for detailed admin responses."""

    pass


class PlatformMedicineSerializer(AdminMedicineSerializer):
    """Admin list/detail serializer for platform medicine endpoints."""

    pass


class MedicineCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating global catalog entries."""

    class Meta:
        model = Medicine
        fields = (
            'generic_name',
            'brand_name',
            'strength',
            'dosage_form',
            'route',
            'manufacturer',
            'pack_size',
            'pack_size_unit',
            'description',
            'nafdac_registration',
        )

    def create(self, validated_data):
        request = self.context.get('request')
        user = request.user if request else None
        created_by_pharmacy = self.context.get('created_by_pharmacy')
        source = self.context.get('source')
        if source is None:
            source = 'ADMIN' if user and user.role in {'SUPER_ADMIN', 'PLATFORM_ADMIN'} else 'PHARMACY'

        try:
            medicine, _ = Medicine.get_or_create_global(
                created_by=user,
                created_by_pharmacy=created_by_pharmacy,
                source=source,
                **validated_data,
            )
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, 'message_dict') else error.messages
            raise serializers.ValidationError(detail) from error
        return medicine


class MedicineUpdateSerializer(AdminMedicineSerializer):
    """Admin update serializer with immutable provenance in its response."""

    class Meta(AdminMedicineSerializer.Meta):
        read_only_fields = (
            'id',
            'source',
            'verification_status',
            'created_by',
            'creator_name',
            'creator_role',
            'created_by_pharmacy',
            'creator_pharmacy',
            'created_at',
            'updated_at',
        )
