"""
Serializers for Medicine model.
"""

from rest_framework import serializers
from .models import Medicine


class MedicineListSerializer(serializers.ModelSerializer):
    """Simplified medicine listing"""
    pharmacy_name = serializers.CharField(source='pharmacy.brand_name', read_only=True)
    
    class Meta:
        model = Medicine
        fields = ('id', 'pharmacy', 'pharmacy_name', 'generic_name', 'brand_name', 'strength', 'dosage_form', 'route')
        read_only_fields = ('id', 'pharmacy', 'pharmacy_name')


class MedicineDetailSerializer(serializers.ModelSerializer):
    """Full medicine details"""
    
    created_by_name = serializers.SerializerMethodField()
    pharmacy_name = serializers.CharField(source='pharmacy.brand_name', read_only=True)
    
    class Meta:
        model = Medicine
        fields = (
            'id', 'pharmacy', 'pharmacy_name', 'generic_name', 'brand_name', 'strength', 'dosage_form',
            'route', 'manufacturer', 'pack_size', 'pack_size_unit',
            'description', 'nafdac_registration', 'created_by', 'created_by_name',
            'created_at', 'updated_at'
        )
        read_only_fields = (
            'id', 'pharmacy', 'created_by', 'created_at', 'updated_at'
        )
    
    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name()
        return None


class MedicineCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating medicines (pharmacy owner only)"""
    
    class Meta:
        model = Medicine
        fields = (
            'generic_name', 'brand_name', 'strength', 'dosage_form',
            'route', 'manufacturer', 'pack_size', 'pack_size_unit',
            'description', 'nafdac_registration'
        )
    
    def create(self, validated_data):
        # Add the current user as creator and their pharmacy
        user = self.context['request'].user
        pharmacy = self.context['pharmacy']
        
        medicine = Medicine.objects.create(
            pharmacy=pharmacy,
            created_by=user,
            **validated_data
        )
        return medicine


class MedicineUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating medicines (pharmacy owner only)"""
    
    class Meta:
        model = Medicine
        fields = (
            'generic_name', 'brand_name', 'strength', 'dosage_form',
            'route', 'manufacturer', 'pack_size', 'pack_size_unit',
            'description', 'nafdac_registration'
        )
