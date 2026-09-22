from decimal import Decimal

from rest_framework import serializers

from inventory.models import InventoryBatch
from medicine.models import Medicine

from .models import Purchase, PurchaseItem, PurchaseReceipt, Supplier


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ('id', 'pharmacy', 'name', 'contact_person', 'phone', 'email', 'address', 'city', 'state', 'registration_information', 'notes', 'status', 'created_by', 'created_at', 'updated_at')
        read_only_fields = ('id', 'pharmacy', 'created_by', 'created_at', 'updated_at')


class PurchaseReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseReceipt
        fields = ('id', 'quantity', 'batch', 'batch_number', 'expiry_date', 'cost_per_unit', 'received_by', 'received_at', 'notes')
        read_only_fields = ('id', 'batch', 'received_by', 'received_at')


class PurchaseItemSerializer(serializers.ModelSerializer):
    medicine_display = serializers.CharField(source='medicine.get_display_name', read_only=True)
    subtotal = serializers.ReadOnlyField()
    remaining_quantity = serializers.ReadOnlyField()
    receipts = PurchaseReceiptSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseItem
        fields = ('id', 'medicine', 'medicine_display', 'quantity_ordered', 'unit_cost', 'subtotal', 'received_quantity', 'remaining_quantity', 'receipts')
        read_only_fields = ('id', 'subtotal', 'received_quantity', 'remaining_quantity', 'receipts')


class PurchaseListSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    item_count = serializers.IntegerField(source='items.count', read_only=True)

    class Meta:
        model = Purchase
        fields = ('id', 'pharmacy', 'supplier', 'supplier_name', 'status', 'subtotal', 'total', 'item_count', 'created_by', 'created_at', 'updated_at')
        read_only_fields = fields


class PurchaseDetailSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    items = PurchaseItemSerializer(many=True, read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Purchase
        fields = ('id', 'pharmacy', 'supplier', 'supplier_name', 'status', 'notes', 'subtotal', 'total', 'created_by', 'created_by_name', 'submitted_at', 'created_at', 'updated_at', 'items')
        read_only_fields = fields

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else None


class PurchaseItemInputSerializer(serializers.Serializer):
    medicine = serializers.PrimaryKeyRelatedField(queryset=Medicine.objects.all())
    quantity_ordered = serializers.IntegerField(min_value=1)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.00'))


class PurchaseCreateSerializer(serializers.Serializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all())
    pharmacy_id = serializers.UUIDField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    items = PurchaseItemInputSerializer(many=True, allow_empty=False)


class ReceivePurchaseSerializer(serializers.Serializer):
    item_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    batch_number = serializers.CharField(max_length=100)
    expiry_date = serializers.DateField()
    cost_per_unit = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.00'))
    notes = serializers.CharField(required=False, allow_blank=True)
