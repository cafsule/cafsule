"""
Sales Business Logic Services

This module contains the core business logic for sale operations:
- SaleCompletionService: Atomic sale completion with batch allocation and stock reduction
- FEFOBatchAllocator: First Expiry First Out batch allocation strategy
- Validation and utility functions
"""

from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.db.models import F, Sum

from .models import Sale, SaleItem, SaleItemBatchAllocation, StockMovement, Customer, CustomerLedgerEntry
from inventory.models import InventoryBatch


class FEFOBatchAllocator:
    """
    First Expiry First Out (FEFO) batch allocation strategy.
    
    Allocates batches in order of earliest expiry date first.
    This is the standard pharmacy batch allocation strategy.
    """
    
    @staticmethod
    def allocate_batches(inventory_item, quantity_needed):
        """
        Allocate batches for a given quantity using FEFO.
        
        Args:
            inventory_item: PharmacyInventoryItem instance
            quantity_needed: Integer quantity to allocate
        
        Returns:
            List of tuples: [(batch, quantity_to_consume), ...]
        
        Raises:
            ValueError: If insufficient valid stock available
        """
        if quantity_needed <= 0:
            raise ValueError("Quantity needed must be greater than 0")
        
        # Get all non-expired batches, ordered by expiry date (FEFO)
        now = timezone.now().date()
        available_batches = InventoryBatch.objects.filter(
            inventory_item=inventory_item,
            expiry_date__gt=now,
            quantity__gt=0
        ).order_by('expiry_date').select_for_update()
        
        allocations = []
        quantity_remaining = quantity_needed
        
        for batch in available_batches:
            if quantity_remaining <= 0:
                break
            
            # Allocate what we can from this batch
            quantity_to_allocate = min(quantity_remaining, batch.quantity)
            allocations.append((batch, quantity_to_allocate))
            quantity_remaining -= quantity_to_allocate
        
        # Check if we were able to fulfill the entire request
        if quantity_remaining > 0:
            total_available = sum(b.quantity for b in available_batches)
            raise ValueError(
                f"Insufficient stock: need {quantity_needed}, "
                f"available {total_available} (all non-expired batches)"
            )
        
        return allocations


class SaleCompletionService:
    """
    Handles the atomic completion of a sale.
    
    Responsibilities:
    1. Validate that the sale can be completed
    2. Validate that inventory/customer/pharmacy are all valid
    3. Verify inventory item prices at completion time
    4. Allocate batches using FEFO strategy
    5. Reduce batch quantities atomically
    6. Create StockMovement records
    7. Update sale status
    
    All of these steps are wrapped in a transaction.atomic() block.
    Row-level locking is used to prevent race conditions.
    """
    
    @staticmethod
    def validate_sale_completable(sale):
        """
        Validate that a sale can be completed.
        
        Raises:
            ValueError: If sale cannot be completed
        """
        if sale.status != 'DRAFT':
            raise ValueError(f"Sale status is {sale.status}, not DRAFT")
        
        if not sale.pharmacy.is_verified:
            raise ValueError(
                f"Pharmacy is {sale.pharmacy.get_verification_status_display()}, "
                "not VERIFIED. Only verified pharmacies can complete sales."
            )
        
        if sale.items.count() == 0:
            raise ValueError("Sale has no items")
    
    @staticmethod
    def validate_sale_item(sale_item):
        """
        Validate a single sale item.
        
        Raises:
            ValueError: If sale item is invalid
        """
        inventory_item = sale_item.inventory_item
        
        # Check that inventory belongs to the same pharmacy
        if inventory_item.pharmacy_id != sale_item.sale.pharmacy_id:
            raise ValueError(
                f"Inventory item belongs to {inventory_item.pharmacy.brand_name}, "
                f"not {sale_item.sale.pharmacy.brand_name}"
            )
        
        # Check that inventory is ACTIVE
        if inventory_item.status != 'ACTIVE':
            raise ValueError(
                f"Inventory item is {inventory_item.get_status_display()}, not ACTIVE"
            )
        
        # Check quantity
        if sale_item.quantity <= 0:
            raise ValueError(f"Sale item quantity must be > 0")
        
        # Check that unit price is positive
        if sale_item.unit_price <= 0:
            raise ValueError(f"Unit price must be > 0")
    
    @staticmethod
    @transaction.atomic
    def complete_sale(sale, user):
        """
        Complete a sale atomically.
        
        This method:
        1. Validates the sale and all items
        2. Allocates batches using FEFO
        3. Reduces batch quantities (with row locking)
        4. Creates StockMovement records
        5. Updates sale status
        
        Args:
            sale: Sale instance
            user: User performing the completion
        
        Raises:
            ValueError: If any validation fails
        
        Returns:
            sale: Updated sale instance
        """
        # Validate sale can be completed
        SaleCompletionService.validate_sale_completable(sale)
        
        # Validate all sale items
        sale_items = sale.items.all()
        for sale_item in sale_items:
            SaleCompletionService.validate_sale_item(sale_item)
        
        # Process each sale item: allocate batches and reduce stock
        for sale_item in sale_items:
            SaleCompletionService._process_sale_item(sale_item, user)
        
        # Mark sale as completed
        sale.complete(user)
        
        return sale
    
    @staticmethod
    def _process_sale_item(sale_item, user):
        """
        Process a single sale item:
        1. Allocate batches using FEFO
        2. Reduce batch quantities atomically
        3. Create StockMovement records
        
        Args:
            sale_item: SaleItem instance
            user: User performing this action
        """
        # Get FEFO-ordered batch allocations
        allocations = FEFOBatchAllocator.allocate_batches(
            sale_item.inventory_item,
            sale_item.quantity
        )
        
        # Lock batches and reduce quantities
        for batch, quantity_to_consume in allocations:
            # Lock the batch with select_for_update
            batch = InventoryBatch.objects.select_for_update().get(pk=batch.pk)
            
            # Verify we still have enough quantity
            if batch.quantity < quantity_to_consume:
                raise ValueError(
                    f"Batch {batch.batch_number} quantity changed during processing. "
                    f"Expected {quantity_to_consume}, available {batch.quantity}"
                )
            
            # Create batch allocation record
            SaleItemBatchAllocation.objects.create(
                sale_item=sale_item,
                batch=batch,
                quantity=quantity_to_consume
            )
            
            # Reduce batch quantity
            batch.quantity -= quantity_to_consume
            batch.save(update_fields=['quantity', 'updated_at'])
            
            # Create immutable stock movement record
            StockMovement.create_sale_movement(
                sale=sale_item.sale,
                sale_item=sale_item,
                batch=batch,
                quantity=quantity_to_consume,
                user=user
            )


class SaleVoidService:
    """Reverse a completed sale while preserving its audit history."""

    @staticmethod
    @transaction.atomic
    def void_sale(sale, user, reason=''):
        locked_sale = Sale.objects.select_for_update().get(pk=sale.pk)
        if locked_sale.status != 'COMPLETED':
            raise ValueError(f"Cannot void sale with status {locked_sale.status}")

        allocations = SaleItemBatchAllocation.objects.filter(
            sale_item__sale=locked_sale
        ).select_related('sale_item', 'batch', 'sale_item__inventory_item')

        for allocation in allocations:
            batch = InventoryBatch.objects.select_for_update().get(pk=allocation.batch_id)
            batch.quantity += allocation.quantity
            batch.save(update_fields=['quantity', 'updated_at'])
            StockMovement.create_void_movement(
                sale=locked_sale,
                sale_item=allocation.sale_item,
                batch=batch,
                quantity=allocation.quantity,
                user=user,
                notes=reason,
            )

        locked_sale.void(user, reason)

        if locked_sale.customer_id and locked_sale.payment_method == 'DEBT':
            customer = Customer.objects.select_for_update().get(pk=locked_sale.customer_id)
            reversal_amount = min(
                customer.outstanding_balance,
                max(Decimal('0.00'), locked_sale.total - locked_sale.amount_paid),
            )
            if reversal_amount > Decimal('0.00'):
                CustomerLedgerEntry.objects.create(
                    customer=customer,
                    pharmacy=locked_sale.pharmacy,
                    sale=locked_sale,
                    entry_type='VOID',
                    amount=reversal_amount,
                    description=f'Voided credit sale {locked_sale.receipt_number}',
                    notes=reason,
                    balance_after=max(Decimal('0.00'), customer.outstanding_balance - reversal_amount),
                    created_by=user,
                )

        return locked_sale


def generate_receipt_number(pharmacy_id):
    """
    Generate a unique receipt number for a pharmacy.
    
    Format: PHARMACY_CODE-TIMESTAMP-SEQUENCE
    
    This ensures uniqueness across time and prevents collisions.
    """
    import uuid
    from django.utils import timezone
    
    timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
    sequence = str(uuid.uuid4().hex[:8]).upper()
    return f"RCP-{timestamp}-{sequence}"


def validate_customer_belongs_to_pharmacy(customer, pharmacy):
    """
    Validate that a customer belongs to a pharmacy.
    
    Raises:
        ValueError: If customer doesn't belong to pharmacy
    """
    if customer is not None and customer.pharmacy_id != pharmacy.id:
        raise ValueError(
            f"Customer does not belong to {pharmacy.brand_name}"
        )


def calculate_sale_totals(sale_items_data):
    """
    Calculate sale totals from sale items data.
    
    This is done server-side to prevent client manipulation.
    
    Args:
        sale_items_data: List of dicts with quantity, unit_price, line_discount
    
    Returns:
        dict: {subtotal, total}
    """
    subtotal = Decimal('0.00')
    
    for item in sale_items_data:
        quantity = Decimal(str(item.get('quantity', 0)))
        unit_price = Decimal(str(item.get('unit_price', '0.00')))
        line_discount = Decimal(str(item.get('line_discount', '0.00')))
        
        line_total = (quantity * unit_price) - line_discount
        subtotal += line_total
    
    return {
        'subtotal': max(subtotal, Decimal('0.00')),
        'total': max(subtotal, Decimal('0.00')),
    }
