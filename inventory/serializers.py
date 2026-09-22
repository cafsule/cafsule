"""
Serializers for Inventory models.
"""

from rest_framework import serializers
from django.utils import timezone
from django.db.models import Sum
from .models import (
    PharmacyInventoryItem, InventoryBatch, CustomerReturn, 
    InventoryHold, StockReconciliation
)
from medicine.models import Medicine
from sales.models import Sale, SaleItem


class InventoryBatchListSerializer(serializers.ModelSerializer):
    """Batch details for listing"""
    
    is_expired = serializers.SerializerMethodField()
    days_until_expiry = serializers.ReadOnlyField()
    
    class Meta:
        model = InventoryBatch
        fields = (
            'id', 'batch_number', 'quantity', 'expiry_date',
            'is_expired', 'days_until_expiry', 'cost_per_unit',
            'created_at'
        )
        read_only_fields = ('id', 'created_at')
    
    def get_is_expired(self, obj):
        return obj.is_expired


class InventoryBatchCreateSerializer(serializers.ModelSerializer):
    """Create/update batch"""
    
    class Meta:
        model = InventoryBatch
        fields = ('batch_number', 'quantity', 'expiry_date', 'cost_per_unit')
    
    def validate_quantity(self, value):
        if value < 0:
            raise serializers.ValidationError("Quantity cannot be negative")
        return value
    
    def validate_expiry_date(self, value):
        from django.utils import timezone
        if value < timezone.now().date():
            raise serializers.ValidationError("Expiry date cannot be in the past")
        return value


class PharmacyInventoryListSerializer(serializers.ModelSerializer):
    """Simplified inventory item listing"""
    
    medicine_display = serializers.SerializerMethodField()
    total_quantity = serializers.ReadOnlyField()
    
    class Meta:
        model = PharmacyInventoryItem
        fields = (
            'id', 'medicine_display', 'selling_price', 'reorder_level', 'status',
            'is_published', 'total_quantity', 'created_at'
        )
        read_only_fields = fields
    
    def get_medicine_display(self, obj):
        return obj.medicine.get_display_name()


class PharmacyInventoryDetailSerializer(serializers.ModelSerializer):
    """Full inventory item details with batches"""
    
    medicine = serializers.PrimaryKeyRelatedField(
        queryset=Medicine.objects.all()
    )
    medicine_display = serializers.SerializerMethodField()
    published_by_name = serializers.SerializerMethodField()
    total_quantity = serializers.ReadOnlyField()
    has_expired_stock = serializers.ReadOnlyField()
    batches = InventoryBatchListSerializer(many=True, read_only=True)
    
    class Meta:
        model = PharmacyInventoryItem
        fields = (
            'id', 'pharmacy', 'medicine', 'medicine_display',
            'selling_price', 'reorder_level', 'status', 'is_published', 'published_at',
            'published_by', 'published_by_name', 'total_quantity',
            'has_expired_stock', 'batches', 'created_at', 'updated_at'
        )
        read_only_fields = (
            'id', 'pharmacy', 'is_published', 'published_at', 'published_by',
            'created_at', 'updated_at'
        )
    
    def get_medicine_display(self, obj):
        return obj.medicine.get_display_name()
    
    def get_published_by_name(self, obj):
        if obj.published_by:
            return obj.published_by.get_full_name()
        return None


class PharmacyInventoryCreateSerializer(serializers.ModelSerializer):
    """Create inventory item"""
    
    medicine = serializers.PrimaryKeyRelatedField(
        queryset=Medicine.objects.all(),
        required=True
    )
    
    class Meta:
        model = PharmacyInventoryItem
        fields = ('medicine', 'selling_price', 'reorder_level', 'status')
    
    def validate_selling_price(self, value):
        from decimal import Decimal
        if value <= Decimal('0'):
            raise serializers.ValidationError("Selling price must be greater than 0")
        return value
    
    def create(self, validated_data):
        # Add pharmacy from request context
        user = self.context['request'].user
        from pharmacy.models import PharmacyMembership
        
        # Determine which pharmacy this inventory belongs to
        # For PHARMACY_OWNER, use their owned pharmacy
        # For staff, use their approved membership pharmacy
        
        if user.role == 'PHARMACY_OWNER':
            try:
                pharmacy = user.owned_pharmacy_brand
            except:
                raise serializers.ValidationError("You do not own a pharmacy")
        else:
            # Staff must have approved membership
            membership = PharmacyMembership.objects.filter(
                user=user,
                status='APPROVED'
            ).first()
            if not membership:
                raise serializers.ValidationError("You are not an approved member of any pharmacy")
            pharmacy = membership.pharmacy
        
        # Check for duplicate
        medicine = validated_data['medicine']
        if PharmacyInventoryItem.objects.filter(pharmacy=pharmacy, medicine=medicine).exists():
            raise serializers.ValidationError(
                f"This pharmacy already has {medicine.get_display_name()} in inventory"
            )
        
        item = PharmacyInventoryItem.objects.create(
            pharmacy=pharmacy,
            created_by=user,
            **validated_data
        )
        return item


class PharmacyInventoryUpdateSerializer(serializers.ModelSerializer):
    """Update inventory item (price and status)"""
    
    class Meta:
        model = PharmacyInventoryItem
        fields = ('selling_price', 'reorder_level', 'status')
    
    def validate_selling_price(self, value):
        from decimal import Decimal
        if value <= Decimal('0'):
            raise serializers.ValidationError("Selling price must be greater than 0")
        return value


class PublishInventorySerializer(serializers.ModelSerializer):
    """Serializer for publishing inventory"""
    
    class Meta:
        model = PharmacyInventoryItem
        fields = ('id', 'is_published', 'published_at', 'published_by')
        read_only_fields = fields


class PublicInventorySerializer(serializers.ModelSerializer):
    """Safe public representation for Smart Medicine Finder discovery."""

    medicine_name = serializers.CharField(source='medicine.get_display_name', read_only=True)
    pharmacy_name = serializers.CharField(source='pharmacy.brand_name', read_only=True)
    city = serializers.CharField(source='pharmacy.city', read_only=True)
    state = serializers.CharField(source='pharmacy.state', read_only=True)
    latitude = serializers.FloatField(source='pharmacy.latitude', read_only=True)
    longitude = serializers.FloatField(source='pharmacy.longitude', read_only=True)
    availability = serializers.SerializerMethodField()

    class Meta:
        model = PharmacyInventoryItem
        fields = ('id', 'medicine', 'medicine_name', 'pharmacy', 'pharmacy_name',
              'city', 'state', 'latitude', 'longitude', 'selling_price',
              'availability', 'published_at')
        read_only_fields = fields

    def get_availability(self, obj):
        from .services import InventoryPublicationService
        return InventoryPublicationService.availability(obj)


# ============================================================================
# Customer Return Serializers
# ============================================================================

class CustomerReturnListSerializer(serializers.ModelSerializer):
    """List view for customer returns"""
    
    sale_number = serializers.CharField(source='sale.receipt_number', read_only=True)
    customer_name = serializers.CharField(source='sale.customer.get_display_name', read_only=True)
    medicine_name = serializers.CharField(
        source='inventory_item.medicine.get_display_name',
        read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    condition_display = serializers.CharField(source='get_condition_display', read_only=True)
    
    class Meta:
        model = CustomerReturn
        fields = (
            'id', 'sale_number', 'customer_name', 'medicine_name', 'quantity_returned',
            'condition', 'condition_display', 'status', 'status_display',
            'created_at'
        )
        read_only_fields = fields


class CustomerReturnDetailSerializer(serializers.ModelSerializer):
    """Detailed view for a customer return"""
    
    sale_number = serializers.CharField(source='sale.receipt_number', read_only=True)
    customer_name = serializers.CharField(source='sale.customer.get_display_name', read_only=True)
    medicine_name = serializers.CharField(
        source='inventory_item.medicine.get_display_name',
        read_only=True
    )
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)
    initiated_by_name = serializers.CharField(
        source='initiated_by.get_full_name',
        read_only=True
    )
    reviewed_by_name = serializers.CharField(
        source='reviewed_by.get_full_name',
        read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    condition_display = serializers.CharField(source='get_condition_display', read_only=True)
    disposition_display = serializers.CharField(source='get_disposition_display', read_only=True)
    
    class Meta:
        model = CustomerReturn
        fields = (
            'id', 'sale', 'sale_number', 'customer_name', 'sale_item', 'inventory_item',
            'medicine_name', 'batch', 'batch_number', 'quantity_returned',
            'condition', 'condition_display', 'reason', 'notes', 'status',
            'status_display', 'disposition', 'disposition_display',
            'initiated_by', 'initiated_by_name', 'reviewed_by', 'reviewed_by_name',
            'created_at', 'reviewed_at'
        )
        read_only_fields = (
            'id', 'sale', 'sale_item', 'inventory_item', 'batch',
            'initiated_by', 'reviewed_by', 'created_at', 'reviewed_at',
            'disposition'
        )


class CustomerReturnInitiateSerializer(serializers.Serializer):
    """Serializer for initiating a customer return"""
    
    sale_id = serializers.UUIDField()
    sale_item_id = serializers.UUIDField()
    quantity_returned = serializers.IntegerField(min_value=1)
    condition = serializers.ChoiceField(
        choices=['SELLABLE', 'DAMAGED', 'QUARANTINED']
    )
    reason = serializers.CharField(max_length=100, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, data):
        try:
            sale = Sale.objects.select_related('pharmacy', 'customer').get(id=data['sale_id'])
            sale_item = SaleItem.objects.get(id=data['sale_item_id'], sale=sale)
        except (Sale.DoesNotExist, SaleItem.DoesNotExist):
            raise serializers.ValidationError("Invalid sale or sale item")
        
        if sale.status != 'COMPLETED':
            raise serializers.ValidationError('Only completed sales can be returned.')

        returned_quantity = CustomerReturn.objects.filter(
            sale_item=sale_item,
            status__in=['PENDING_REVIEW', 'APPROVED', 'COMPLETED'],
        ).aggregate(total=Sum('quantity_returned'))['total'] or 0
        remaining_quantity = sale_item.quantity - returned_quantity
        if data['quantity_returned'] > remaining_quantity:
            raise serializers.ValidationError(
                f"Cannot return {data['quantity_returned']}; only {remaining_quantity} units remain returnable."
            )
        
        data['sale'] = sale
        data['sale_item'] = sale_item
        return data


class CustomerReturnApproveSerializer(serializers.Serializer):
    """Serializer for approving a return"""
    
    action = serializers.ChoiceField(choices=['APPROVE', 'REJECT'])
    reason = serializers.CharField(required=False, allow_blank=True)


# ============================================================================
# Inventory Hold Serializers
# ============================================================================

class InventoryHoldListSerializer(serializers.ModelSerializer):
    """List view for inventory holds"""
    
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)
    medicine_name = serializers.CharField(
        source='inventory_item.medicine.get_display_name',
        read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = InventoryHold
        fields = (
            'id', 'medicine_name', 'batch_number', 'quantity',
            'reason', 'status', 'status_display', 'created_at'
        )
        read_only_fields = fields


class InventoryHoldDetailSerializer(serializers.ModelSerializer):
    """Detailed view for an inventory hold"""
    
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)
    medicine_name = serializers.CharField(
        source='inventory_item.medicine.get_display_name',
        read_only=True
    )
    initiated_by_name = serializers.CharField(
        source='initiated_by.get_full_name',
        read_only=True
    )
    resolved_by_name = serializers.CharField(
        source='resolved_by.get_full_name',
        read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    resolution_display = serializers.CharField(source='get_resolution_display', read_only=True)
    
    class Meta:
        model = InventoryHold
        fields = (
            'id', 'batch', 'batch_number', 'inventory_item', 'medicine_name',
            'quantity', 'reason', 'notes', 'status', 'status_display',
            'resolution', 'resolution_display', 'initiated_by', 'initiated_by_name',
            'resolved_by', 'resolved_by_name', 'created_at', 'resolved_at',
            'reference_type', 'reference_id'
        )
        read_only_fields = (
            'id', 'batch', 'inventory_item', 'initiated_by', 'resolved_by',
            'created_at', 'resolved_at', 'reference_type', 'reference_id'
        )


class InventoryHoldResolveSerializer(serializers.Serializer):
    """Serializer for resolving an inventory hold"""
    
    resolution = serializers.ChoiceField(
        choices=['RETURN_TO_STOCK', 'MARK_DAMAGED', 'MARK_EXPIRED', 'WRITE_OFF', 'OTHER']
    )
    quantity = serializers.IntegerField(min_value=1)
    notes = serializers.CharField(required=False, allow_blank=True)


# ============================================================================
# Stock Adjustment Serializers
# ============================================================================

class StockAdjustmentSerializer(serializers.Serializer):
    """Serializer for stock adjustments"""
    
    inventory_item_id = serializers.UUIDField()
    batch_id = serializers.UUIDField()
    quantity_delta = serializers.IntegerField()  # Can be positive or negative
    reason = serializers.CharField(max_length=50)
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate_reason(self, value):
        valid_reasons = [
            'STOCK_COUNT_CORRECTION', 'DATA_ENTRY_ERROR', 'FOUND',
            'ADJUSTMENT_OTHER', 'OTHER'
        ]
        if value not in valid_reasons:
            raise serializers.ValidationError(f"Invalid reason: {value}")
        return value
    
    def validate(self, data):
        if data['quantity_delta'] == 0:
            raise serializers.ValidationError("Quantity delta must not be zero")
        
        try:
            item = PharmacyInventoryItem.objects.get(id=data['inventory_item_id'])
            batch = InventoryBatch.objects.get(id=data['batch_id'], inventory_item=item)
        except (PharmacyInventoryItem.DoesNotExist, InventoryBatch.DoesNotExist):
            raise serializers.ValidationError("Invalid inventory item or batch")
        
        data['inventory_item'] = item
        data['batch'] = batch
        return data


class DamageRecordSerializer(serializers.Serializer):
    """Serializer for recording damage"""
    
    inventory_item_id = serializers.UUIDField()
    batch_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=50)
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate_reason(self, value):
        valid_reasons = [
            'DAMAGED_IN_STORAGE', 'DAMAGED_IN_DELIVERY', 'QUALITY_ISSUE',
            'PACKAGING_COMPROMISED', 'DAMAGE_OTHER'
        ]
        if value not in valid_reasons:
            raise serializers.ValidationError(f"Invalid reason: {value}")
        return value
    
    def validate(self, data):
        try:
            item = PharmacyInventoryItem.objects.get(id=data['inventory_item_id'])
            batch = InventoryBatch.objects.get(id=data['batch_id'], inventory_item=item)
        except (PharmacyInventoryItem.DoesNotExist, InventoryBatch.DoesNotExist):
            raise serializers.ValidationError("Invalid inventory item or batch")
        
        data['inventory_item'] = item
        data['batch'] = batch
        return data


class ExpiryRecordSerializer(serializers.Serializer):
    """Serializer for recording expiry"""
    
    inventory_item_id = serializers.UUIDField()
    batch_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=50)
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate_reason(self, value):
        valid_reasons = ['NATURAL_EXPIRY', 'RECALLED', 'DAMAGED_EXPIRY']
        if value not in valid_reasons:
            raise serializers.ValidationError(f"Invalid reason: {value}")
        return value
    
    def validate(self, data):
        try:
            item = PharmacyInventoryItem.objects.get(id=data['inventory_item_id'])
            batch = InventoryBatch.objects.get(id=data['batch_id'], inventory_item=item)
        except (PharmacyInventoryItem.DoesNotExist, InventoryBatch.DoesNotExist):
            raise serializers.ValidationError("Invalid inventory item or batch")
        
        if batch.expiry_date > timezone.now().date():
            raise serializers.ValidationError("Batch is not expired yet")
        
        data['inventory_item'] = item
        data['batch'] = batch
        return data


class LossRecordSerializer(serializers.Serializer):
    """Serializer for recording loss"""
    
    inventory_item_id = serializers.UUIDField()
    batch_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=50)
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate_reason(self, value):
        valid_reasons = ['MISSING_INVENTORY', 'SUSPECTED_THEFT', 'UNKNOWN_LOSS']
        if value not in valid_reasons:
            raise serializers.ValidationError(f"Invalid reason: {value}")
        return value
    
    def validate(self, data):
        try:
            item = PharmacyInventoryItem.objects.get(id=data['inventory_item_id'])
            batch = InventoryBatch.objects.get(id=data['batch_id'], inventory_item=item)
        except (PharmacyInventoryItem.DoesNotExist, InventoryBatch.DoesNotExist):
            raise serializers.ValidationError("Invalid inventory item or batch")
        
        data['inventory_item'] = item
        data['batch'] = batch
        return data


# ============================================================================
# Stock Reconciliation Serializers
# ============================================================================

class StockReconciliationListSerializer(serializers.ModelSerializer):
    """List view for stock reconciliations"""
    
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)
    medicine_name = serializers.CharField(
        source='inventory_item.medicine.get_display_name',
        read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = StockReconciliation
        fields = (
            'id', 'batch_number', 'medicine_name', 'expected_quantity',
            'counted_quantity', 'difference', 'status', 'status_display',
            'created_at'
        )
        read_only_fields = fields


class StockReconciliationDetailSerializer(serializers.ModelSerializer):
    """Detailed view for a stock reconciliation"""
    
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)
    medicine_name = serializers.CharField(
        source='inventory_item.medicine.get_display_name',
        read_only=True
    )
    counted_by_name = serializers.CharField(
        source='counted_by.get_full_name',
        read_only=True
    )
    approved_by_name = serializers.CharField(
        source='approved_by.get_full_name',
        read_only=True
    )
    reconciled_by_name = serializers.CharField(
        source='reconciled_by.get_full_name',
        read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    discrepancy_type_display = serializers.CharField(
        source='get_discrepancy_type_display',
        read_only=True
    )
    
    class Meta:
        model = StockReconciliation
        fields = (
            'id', 'pharmacy', 'inventory_item', 'batch', 'batch_number',
            'medicine_name', 'expected_quantity', 'expected_quantity_captured_at',
            'counted_quantity', 'counted_at', 'counted_by', 'counted_by_name',
            'difference', 'discrepancy_type', 'discrepancy_type_display',
            'reason_for_discrepancy', 'notes', 'status', 'status_display',
            'approved_by', 'approved_by_name', 'approved_at', 'approval_notes',
            'reconciled_by', 'reconciled_by_name', 'reconciled_at',
            'resulting_movement_id', 'created_at'
        )
        read_only_fields = (
            'id', 'pharmacy', 'inventory_item', 'batch', 'expected_quantity',
            'expected_quantity_captured_at', 'counted_by', 'difference',
            'discrepancy_type', 'approved_by', 'reconciled_by',
            'created_at', 'counted_at', 'approved_at', 'reconciled_at',
            'resulting_movement_id'
        )


class StockReconciliationStartSerializer(serializers.Serializer):
    """Serializer for starting a count"""
    
    inventory_item_id = serializers.UUIDField()
    batch_id = serializers.UUIDField()
    
    def validate(self, data):
        try:
            item = PharmacyInventoryItem.objects.get(id=data['inventory_item_id'])
            batch = InventoryBatch.objects.get(id=data['batch_id'], inventory_item=item)
        except (PharmacyInventoryItem.DoesNotExist, InventoryBatch.DoesNotExist):
            raise serializers.ValidationError("Invalid inventory item or batch")
        
        data['inventory_item'] = item
        data['batch'] = batch
        return data


class StockReconciliationCountSerializer(serializers.Serializer):
    """Serializer for submitting a count"""
    
    counted_quantity = serializers.IntegerField(min_value=0)


class StockReconciliationApproveSerializer(serializers.Serializer):
    """Serializer for approving a count"""
    
    approval_notes = serializers.CharField(required=False, allow_blank=True)
