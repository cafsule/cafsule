"""
Serializers for Sales API.

Handles serialization of:
- Sale (create, list, detail, update, complete, void)
- SaleItem (create, list, detail)
- Customer (create, list, detail)
- StockMovement (list, detail - read-only)
"""

from decimal import Decimal
from rest_framework import serializers
from django.db import transaction
from django.utils import timezone

from .models import (
    Sale, SaleItem, SaleItemBatchAllocation, Customer, StockMovement,
    CustomerPayment, CustomerLedgerEntry
)
from inventory.models import PharmacyInventoryItem, InventoryBatch
from pharmacy.models import PharmacyBrand


class CustomerSerializer(serializers.ModelSerializer):
    """Customer read and write serializer with ledger totals."""

    total_sales = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
        min_value=Decimal('0.00')
    )
    total_paid = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
        min_value=Decimal('0.00')
    )
    outstanding_balance = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
        min_value=Decimal('0.00')
    )
    sales_count = serializers.IntegerField(read_only=True)
    last_purchase_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Customer
        fields = (
            'id', 'first_name', 'last_name', 'phone_number', 'email',
            'customer_type', 'created_at', 'total_sales', 'total_paid',
            'outstanding_balance', 'sales_count', 'last_purchase_at'
        )
        read_only_fields = ('id', 'created_at', 'total_sales', 'total_paid', 'outstanding_balance', 'sales_count', 'last_purchase_at')

    def validate_phone_number(self, value):
        if value and len(value) < 10:
            raise serializers.ValidationError("Phone number must be at least 10 digits")
        return value


class CustomerLedgerEntrySerializer(serializers.ModelSerializer):
    """Ledger transaction for a customer's account."""

    entry_type_display = serializers.CharField(source='get_entry_type_display', read_only=True)

    class Meta:
        model = CustomerLedgerEntry
        fields = (
            'id', 'entry_type', 'entry_type_display', 'amount', 'description',
            'notes', 'balance_after', 'created_at', 'sale', 'payment'
        )
        read_only_fields = fields


class CustomerPaymentSerializer(serializers.ModelSerializer):
    """Record a customer payment against the pharmacy account."""

    class Meta:
        model = CustomerPayment
        fields = (
            'id', 'customer', 'pharmacy', 'sale', 'amount', 'payment_method',
            'reference', 'notes', 'recorded_by', 'created_at'
        )
        read_only_fields = ('id', 'customer', 'pharmacy', 'recorded_by', 'created_at')

    def validate_amount(self, value):
        if value <= Decimal('0.00'):
            raise serializers.ValidationError('Payment amount must be greater than zero.')
        return value

    def validate(self, data):
        customer = self.context.get('customer')
        if customer is None:
            raise serializers.ValidationError('Customer is required.')

        payment_method = data.get('payment_method', 'CASH')
        valid_methods = {choice[0] for choice in CustomerPayment.PAYMENT_METHOD_CHOICES}
        if payment_method not in valid_methods:
            raise serializers.ValidationError('Unsupported payment method.')
        if payment_method == 'DEBT':
            raise serializers.ValidationError('Debt is not a repayment method.')

        amount = data.get('amount', Decimal('0.00'))
        if amount > customer.outstanding_balance:
            raise serializers.ValidationError('Payment cannot exceed the outstanding balance.')

        return data


class StockMovementSerializer(serializers.ModelSerializer):
    """Read-only serializer for stock movements"""
    
    movement_type_display = serializers.CharField(
        source='get_movement_type_display',
        read_only=True
    )
    
    class Meta:
        model = StockMovement
        fields = (
            'id', 'movement_type', 'movement_type_display', 'pharmacy',
            'inventory_item', 'batch', 'quantity_change', 'sale', 'sale_item',
            'performed_by', 'notes', 'created_at'
        )
        read_only_fields = fields


class SaleItemBatchAllocationSerializer(serializers.ModelSerializer):
    """Serializer for batch allocations within a sale item"""
    
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)
    expiry_date = serializers.DateField(source='batch.expiry_date', read_only=True)
    
    class Meta:
        model = SaleItemBatchAllocation
        fields = ('id', 'batch', 'batch_number', 'expiry_date', 'quantity', 'created_at')
        read_only_fields = ('id', 'created_at')


class SaleItemDetailSerializer(serializers.ModelSerializer):
    """Detailed sale item serializer with batch allocations"""
    
    medicine_name = serializers.CharField(
        source='inventory_item.medicine.get_display_name',
        read_only=True
    )
    batch_allocations = SaleItemBatchAllocationSerializer(
        source='batch_allocations_rel',
        many=True,
        read_only=True
    )
    
    class Meta:
        model = SaleItem
        fields = (
            'id', 'sale', 'inventory_item', 'medicine_name', 'quantity',
            'unit_price', 'line_discount', 'line_total', 'batch_allocations',
            'created_at'
        )
        read_only_fields = (
            'id', 'sale', 'unit_price', 'line_total', 'batch_allocations',
            'created_at'
        )


class SaleItemCreateUpdateSerializer(serializers.Serializer):
    """
    Serializer for creating/updating sale items.
    
    Note: This is NOT a ModelSerializer because we need to:
    1. Accept inventory_item ID from client
    2. Look up current price from inventory configuration
    3. Server-side price validation
    4. Calculate line totals server-side
    """
    
    inventory_item_id = serializers.UUIDField(
        help_text="UUID of the PharmacyInventoryItem"
    )
    quantity = serializers.IntegerField(
        min_value=1,
        help_text="Quantity to sell"
    )
    line_discount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        min_value=Decimal('0.00'),
        help_text="Discount on this line"
    )
    
    def validate_inventory_item_id(self, value):
        """Validate that the inventory item exists and belongs to the pharmacy"""
        try:
            item = PharmacyInventoryItem.objects.get(id=value)
        except PharmacyInventoryItem.DoesNotExist:
            raise serializers.ValidationError("Inventory item not found")
        
        # Will check pharmacy ownership in validate()
        return item
    
    def validate(self, data):
        """
        Validate and enrich sale item data.
        
        Server-side:
        - Verify inventory belongs to the sale's pharmacy
        - Get current selling price from inventory
        - Calculate line total
        - Validate stock availability
        """
        inventory_item = data.get('inventory_item_id')
        quantity = data.get('quantity')
        line_discount = data.get('line_discount', Decimal('0.00'))
        
        # Get pharmacy from context
        sale_id = self.context.get('sale_id')
        if sale_id:
            try:
                sale = Sale.objects.get(id=sale_id)
                pharmacy = sale.pharmacy
            except Sale.DoesNotExist:
                raise serializers.ValidationError("Sale not found")
        else:
            # During sale creation, pharmacy comes from context
            pharmacy = self.context.get('pharmacy')
        
        # Verify inventory belongs to pharmacy
        if inventory_item.pharmacy_id != pharmacy.id:
            raise serializers.ValidationError(
                f"Inventory item does not belong to {pharmacy.brand_name}"
            )
        
        # Verify inventory is ACTIVE
        if inventory_item.status != 'ACTIVE':
            raise serializers.ValidationError(
                f"Inventory item is {inventory_item.get_status_display()}"
            )
        
        # Get server-side price
        unit_price = inventory_item.selling_price
        
        # Calculate line total
        line_total = (Decimal(str(quantity)) * unit_price) - line_discount
        
        # Validate discount doesn't exceed line total
        if line_discount > (Decimal(str(quantity)) * unit_price):
            raise serializers.ValidationError(
                f"Line discount cannot exceed {Decimal(str(quantity)) * unit_price}"
            )
        
        # For DRAFT sales (not yet completed), we don't check stock
        # Stock is validated during sale completion
        
        # Store server-side values in data
        data['unit_price'] = unit_price
        data['line_total'] = line_total
        
        return data


class SaleListSerializer(serializers.ModelSerializer):
    """Simplified sale serializer for list view"""
    
    pharmacy_name = serializers.CharField(
        source='pharmacy.brand_name',
        read_only=True
    )
    customer_name = serializers.CharField(
        source='customer.get_display_name',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    item_count = serializers.ReadOnlyField()
    
    class Meta:
        model = Sale
        fields = (
            'id', 'receipt_number', 'pharmacy', 'pharmacy_name', 'customer',
            'customer_name', 'status', 'status_display', 'total', 'payment_status',
            'item_count', 'created_at'
        )
        read_only_fields = fields


class SaleDetailSerializer(serializers.ModelSerializer):
    """Full sale details with items and movements"""
    
    pharmacy_name = serializers.CharField(
        source='pharmacy.brand_name',
        read_only=True
    )
    customer_name = serializers.CharField(
        source='customer.get_display_name',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    payment_status_display = serializers.CharField(
        source='get_payment_status_display',
        read_only=True
    )
    items = SaleItemDetailSerializer(many=True, read_only=True)
    stock_movements = StockMovementSerializer(many=True, read_only=True)
    
    class Meta:
        model = Sale
        fields = (
            'id', 'receipt_number', 'pharmacy', 'pharmacy_name', 'customer',
            'customer_name', 'status', 'status_display', 'subtotal', 'discount',
            'tax', 'total', 'payment_status', 'payment_status_display',
            'payment_method', 'amount_paid', 'notes', 'sold_by', 'created_at',
            'created_by', 'completed_at', 'voided_at', 'voided_by', 'void_reason',
            'items', 'stock_movements', 'updated_at'
        )
        read_only_fields = fields


class SaleCreateSerializer(serializers.ModelSerializer):
    """Create a new sale (DRAFT status)"""
    
    customer_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional customer ID for non-walk-in sales"
    )
    
    class Meta:
        model = Sale
        fields = (
            'id', 'receipt_number', 'customer_id', 'payment_method',
            'notes'
        )
        read_only_fields = (
            'id', 'receipt_number', 'pharmacy', 'status', 'subtotal',
            'discount', 'tax', 'total', 'payment_status', 'amount_paid',
            'sold_by', 'created_at', 'created_by', 'completed_at'
        )
    
    def create(self, validated_data):
        """
        Create a new sale in DRAFT status.
        
        Server-side:
        - Set pharmacy from authenticated user
        - Generate receipt number
        - Initialize financial fields to zero
        """
        user = self.context['request'].user
        customer_id = validated_data.get('customer_id')
        
        # Determine pharmacy
        if user.role == 'PHARMACY_OWNER':
            try:
                pharmacy = user.owned_pharmacy_brand
            except:
                raise serializers.ValidationError("User does not own a pharmacy")
        else:
            # Get pharmacy from approved membership
            from pharmacy.models import PharmacyMembership
            membership = PharmacyMembership.objects.filter(
                user=user,
                status='APPROVED'
            ).first()
            if not membership:
                raise serializers.ValidationError("User is not an approved member of any pharmacy")
            pharmacy = membership.pharmacy
        
        # Verify pharmacy is VERIFIED
        if pharmacy.verification_status != 'VERIFIED':
            raise serializers.ValidationError(
                f"Pharmacy is {pharmacy.get_verification_status_display()}, not VERIFIED"
            )
        
        # Validate customer if provided
        customer = None
        if customer_id:
            try:
                customer = Customer.objects.get(id=customer_id, pharmacy=pharmacy)
            except Customer.DoesNotExist:
                raise serializers.ValidationError("Customer not found or does not belong to this pharmacy")
        
        # Generate receipt number
        from .services import generate_receipt_number
        receipt_number = generate_receipt_number(pharmacy.id)
        
        # Create sale in DRAFT status
        sale = Sale.objects.create(
            pharmacy=pharmacy,
            customer=customer,
            receipt_number=receipt_number,
            status='DRAFT',
            subtotal=Decimal('0.00'),
            discount=Decimal('0.00'),
            tax=Decimal('0.00'),
            total=Decimal('0.00'),
            payment_method=validated_data.get('payment_method', ''),
            notes=validated_data.get('notes', ''),
            created_by=user
        )
        
        return sale


class SaleUpdateSerializer(serializers.ModelSerializer):
    """Update an existing DRAFT sale"""
    
    class Meta:
        model = Sale
        fields = (
            'payment_method', 'payment_status', 'amount_paid', 'notes'
        )
    
    def validate(self, data):
        """Ensure we're only updating a DRAFT sale"""
        if self.instance.status != 'DRAFT':
            raise serializers.ValidationError(
                f"Cannot update sale with status {self.instance.status}"
            )
        return data


class SaleCompleteSerializer(serializers.Serializer):
    """
    Request serializer for completing a sale.
    
    The response is the updated SaleDetailSerializer.
    """
    
    payment_status = serializers.ChoiceField(
        choices=['PENDING', 'PAID', 'PARTIAL', 'CANCELLED'],
        required=False,
        help_text="Final payment status for the sale"
    )
    
    amount_paid = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        help_text="Amount actually paid"
    )


class SaleVoidSerializer(serializers.Serializer):
    """
    Request serializer for voiding a sale.
    
    The response is the updated SaleDetailSerializer.
    """
    
    void_reason = serializers.CharField(
        max_length=500,
        required=True,
        help_text="Reason for voiding this sale"
    )
