"""
Inventory Management Services

This module contains business logic for inventory operations:
- StockAdjustmentService: Manual stock adjustments
- DamageService: Record damage
- ExpiryService: Record expiry write-off
- LossService: Record loss/missing stock
- CustomerReturnService: Process customer returns
- StockReconciliationService: Physical stock counts and reconciliation

All operations are atomic, use row-level locking, and create immutable
StockMovement audit trails.
"""

from django.db import transaction
from django.db.models import Exists, OuterRef, Sum
from django.utils import timezone
from decimal import Decimal

from pharmacy.models import PharmacyBrand
from sales.models import StockMovement, CustomerLedgerEntry
from .models import (
    InventoryBatch,
    PharmacyInventoryItem,
    CustomerReturn,
    InventoryHold,
    StockReconciliation,
)


class InventoryPublicationService:
    """Business operations for owner-controlled public listings."""

    @staticmethod
    def _validate_owner(user, item):
        if not user.is_active:
            raise PermissionError('User is not active')
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return
        if user.role != 'PHARMACY_OWNER' or item.pharmacy.owner_id != user.id:
            raise PermissionError('Only the pharmacy owner can manage publication')

    @staticmethod
    @transaction.atomic
    def publish_inventory(item, user):
        item = PharmacyInventoryItem.objects.select_for_update().select_related('pharmacy').get(pk=item.pk)
        InventoryPublicationService._validate_owner(user, item)
        item.publish(user)
        return item

    @staticmethod
    @transaction.atomic
    def unpublish_inventory(item, user):
        item = PharmacyInventoryItem.objects.select_for_update().select_related('pharmacy').get(pk=item.pk)
        InventoryPublicationService._validate_owner(user, item)
        item.unpublish(user)
        return item

    @staticmethod
    @transaction.atomic
    def update_public_price(item, price, user):
        item = PharmacyInventoryItem.objects.select_for_update().select_related('pharmacy').get(pk=item.pk)
        InventoryPublicationService._validate_owner(user, item)
        if price < Decimal('0'):
            raise ValueError('Public price cannot be negative')
        if item.is_published and price <= Decimal('0'):
            raise ValueError('Published inventory requires a positive public price')
        item.selling_price = price
        item.save(update_fields=['selling_price', 'updated_at'])
        return item

    @staticmethod
    def public_queryset():
        sellable_batch = InventoryBatch.objects.filter(
            inventory_item=OuterRef('pk'),
            expiry_date__gt=timezone.now().date(),
            quantity__gt=0,
        )
        return PharmacyInventoryItem.objects.filter(
            is_published=True,
            status='ACTIVE',
            pharmacy__verification_status='VERIFIED',
        ).annotate(has_sellable_stock=Exists(sellable_batch)).select_related('medicine', 'pharmacy')

    @staticmethod
    def availability(item):
        return 'AVAILABLE' if item.has_sellable_stock else 'OUT_OF_STOCK'


class StockAdjustmentService:
    """Service for manual stock adjustments."""
    
    @staticmethod
    def validate_permissions(user, pharmacy):
        """
        Validate user can adjust stock for this pharmacy.
        
        Raises:
            PermissionError: If user lacks permission
        """
        from auth.models import User as AuthUser
        
        if not user.is_active:
            raise PermissionError("User is not active")
        
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        if user.role == 'PHARMACY_OWNER':
            if not hasattr(user, 'owned_pharmacy_brand'):
                raise PermissionError("User is not a pharmacy owner")
            if user.owned_pharmacy_brand.id != pharmacy.id:
                raise PermissionError("User does not own this pharmacy")
            return True
        
        if user.role in ('PHARMACY_MANAGER',):
            # Check membership
            from pharmacy.models import PharmacyMembership
            membership = PharmacyMembership.objects.filter(
                user=user,
                pharmacy=pharmacy,
                status='APPROVED'
            ).exists()
            if not membership:
                raise PermissionError("User does not have approved membership for this pharmacy")
            return True
        
        raise PermissionError(f"Role {user.role} cannot adjust stock")
    
    @staticmethod
    @transaction.atomic
    def adjust_stock(inventory_item, batch, quantity_delta, reason, user, notes=''):
        """
        Adjust stock quantity.
        
        Args:
            inventory_item: PharmacyInventoryItem
            batch: InventoryBatch
            quantity_delta: Change in quantity (positive or negative)
            reason: Reason for adjustment (from StockMovement.REASON_CHOICES)
            user: User performing adjustment
            notes: Optional notes
        
        Raises:
            ValueError: If validation fails
            PermissionError: If user lacks permission
        
        Returns:
            StockMovement: Created movement record
        """
        # Validate permissions
        StockAdjustmentService.validate_permissions(user, inventory_item.pharmacy)
        
        # Validate quantity_delta
        if quantity_delta == 0:
            raise ValueError("Quantity delta must not be zero")
        
        # Lock batch
        batch = InventoryBatch.objects.select_for_update().get(pk=batch.pk)
        
        # Verify new quantity won't be negative
        new_quantity = batch.quantity + quantity_delta
        if new_quantity < 0:
            raise ValueError(
                f"Adjustment would result in negative stock: "
                f"{batch.quantity} + {quantity_delta} = {new_quantity}"
            )
        
        # Update batch
        batch.quantity = new_quantity
        batch.save(update_fields=['quantity', 'updated_at'])
        
        # Create StockMovement
        movement = StockMovement.objects.create(
            movement_type='ADJUSTMENT',
            pharmacy=inventory_item.pharmacy,
            inventory_item=inventory_item,
            batch=batch,
            quantity_change=quantity_delta,
            reason=reason,
            performed_by=user,
            notes=notes,
        )
        
        return movement


class DamageService:
    """Service for recording damaged stock."""
    
    @staticmethod
    def validate_permissions(user, pharmacy):
        """Validate user can record damage for this pharmacy."""
        if not user.is_active:
            raise PermissionError("User is not active")
        
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        if user.role == 'PHARMACY_OWNER':
            if not hasattr(user, 'owned_pharmacy_brand'):
                raise PermissionError("User is not a pharmacy owner")
            if user.owned_pharmacy_brand.id != pharmacy.id:
                raise PermissionError("User does not own this pharmacy")
            return True
        
        if user.role in ('PHARMACY_MANAGER', 'PHARMACIST'):
            from pharmacy.models import PharmacyMembership
            membership = PharmacyMembership.objects.filter(
                user=user,
                pharmacy=pharmacy,
                status='APPROVED'
            ).exists()
            if not membership:
                raise PermissionError("User does not have approved membership")
            return True
        
        raise PermissionError(f"Role {user.role} cannot record damage")
    
    @staticmethod
    @transaction.atomic
    def record_damage(inventory_item, batch, quantity, reason, user, notes=''):
        """
        Record damaged stock.
        
        Args:
            inventory_item: PharmacyInventoryItem
            batch: InventoryBatch
            quantity: Quantity damaged (positive integer)
            reason: Reason (DAMAGED_IN_STORAGE, QUALITY_ISSUE, etc.)
            user: User recording damage
            notes: Optional notes
        
        Returns:
            StockMovement: Created movement record
        """
        DamageService.validate_permissions(user, inventory_item.pharmacy)
        
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        
        # Lock batch
        batch = InventoryBatch.objects.select_for_update().get(pk=batch.pk)
        
        # Verify sufficient quantity
        if batch.quantity < quantity:
            raise ValueError(
                f"Insufficient stock to mark as damage: "
                f"have {batch.quantity}, trying to damage {quantity}"
            )
        
        # Update batch
        batch.quantity -= quantity
        batch.save(update_fields=['quantity', 'updated_at'])
        
        # Create StockMovement
        movement = StockMovement.objects.create(
            movement_type='DAMAGE',
            pharmacy=inventory_item.pharmacy,
            inventory_item=inventory_item,
            batch=batch,
            quantity_change=-quantity,
            reason=reason,
            performed_by=user,
            notes=notes,
        )
        
        return movement


class ExpiryService:
    """Service for recording expired stock write-off."""
    
    @staticmethod
    def validate_permissions(user, pharmacy):
        """Validate permissions."""
        if not user.is_active:
            raise PermissionError("User is not active")
        
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN', 'PHARMACY_OWNER'):
            if user.role == 'PHARMACY_OWNER':
                if not hasattr(user, 'owned_pharmacy_brand'):
                    raise PermissionError("User is not a pharmacy owner")
                if user.owned_pharmacy_brand.id != pharmacy.id:
                    raise PermissionError("User does not own this pharmacy")
            return True
        
        if user.role in ('PHARMACY_MANAGER', 'PHARMACIST'):
            from pharmacy.models import PharmacyMembership
            membership = PharmacyMembership.objects.filter(
                user=user,
                pharmacy=pharmacy,
                status='APPROVED'
            ).exists()
            if not membership:
                raise PermissionError("User does not have approved membership")
            return True
        
        raise PermissionError(f"Role {user.role} cannot record expiry")
    
    @staticmethod
    @transaction.atomic
    def record_expiry_writeoff(inventory_item, batch, quantity, reason, user, notes=''):
        """
        Record expired stock write-off.
        
        Args:
            inventory_item: PharmacyInventoryItem
            batch: InventoryBatch (must be expired)
            quantity: Quantity written off
            reason: Reason (NATURAL_EXPIRY, RECALLED, etc.)
            user: User recording
            notes: Optional notes
        
        Returns:
            StockMovement: Created movement record
        """
        ExpiryService.validate_permissions(user, inventory_item.pharmacy)
        
        # Validate batch is actually expired
        if batch.expiry_date > timezone.now().date():
            raise ValueError(
                f"Batch is not expired yet (expires {batch.expiry_date})"
            )
        
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        
        # Lock batch
        batch = InventoryBatch.objects.select_for_update().get(pk=batch.pk)
        
        # Verify sufficient quantity
        if batch.quantity < quantity:
            raise ValueError(
                f"Insufficient stock to write off: "
                f"have {batch.quantity}, trying to write off {quantity}"
            )
        
        # Update batch
        batch.quantity -= quantity
        batch.save(update_fields=['quantity', 'updated_at'])
        
        # Create StockMovement
        movement = StockMovement.objects.create(
            movement_type='EXPIRED',
            pharmacy=inventory_item.pharmacy,
            inventory_item=inventory_item,
            batch=batch,
            quantity_change=-quantity,
            reason=reason,
            performed_by=user,
            notes=notes,
        )
        
        return movement


class LossService:
    """Service for recording lost/missing stock."""
    
    @staticmethod
    def validate_permissions(user, pharmacy):
        """Validate permissions."""
        if not user.is_active:
            raise PermissionError("User is not active")
        
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        if user.role == 'PHARMACY_OWNER':
            if not hasattr(user, 'owned_pharmacy_brand'):
                raise PermissionError("User is not a pharmacy owner")
            if user.owned_pharmacy_brand.id != pharmacy.id:
                raise PermissionError("User does not own this pharmacy")
            return True
        
        if user.role == 'PHARMACY_MANAGER':
            from pharmacy.models import PharmacyMembership
            membership = PharmacyMembership.objects.filter(
                user=user,
                pharmacy=pharmacy,
                status='APPROVED'
            ).exists()
            if not membership:
                raise PermissionError("User does not have approved membership")
            return True
        
        raise PermissionError(f"Role {user.role} cannot record loss")
    
    @staticmethod
    @transaction.atomic
    def record_loss(inventory_item, batch, quantity, reason, user, notes=''):
        """
        Record lost/missing stock.
        
        Args:
            inventory_item: PharmacyInventoryItem
            batch: InventoryBatch
            quantity: Quantity missing
            reason: Reason (SUSPECTED_THEFT, UNKNOWN_LOSS, etc.)
            user: User reporting
            notes: Optional notes
        
        Returns:
            StockMovement: Created movement record
        """
        LossService.validate_permissions(user, inventory_item.pharmacy)
        
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        
        # Lock batch
        batch = InventoryBatch.objects.select_for_update().get(pk=batch.pk)
        
        # Verify sufficient quantity
        if batch.quantity < quantity:
            raise ValueError(
                f"Cannot record loss greater than available: "
                f"have {batch.quantity}, loss {quantity}"
            )
        
        # Update batch
        batch.quantity -= quantity
        batch.save(update_fields=['quantity', 'updated_at'])
        
        # Create StockMovement
        movement = StockMovement.objects.create(
            movement_type='LOSS',
            pharmacy=inventory_item.pharmacy,
            inventory_item=inventory_item,
            batch=batch,
            quantity_change=-quantity,
            reason=reason,
            performed_by=user,
            notes=notes,
        )
        
        return movement


class CustomerReturnService:
    """Service for processing customer returns."""
    
    @staticmethod
    def validate_permissions(user, pharmacy, action='initiate'):
        """
        Validate permissions based on action.
        
        Args:
            user: User object
            pharmacy: PharmacyBrand
            action: 'initiate', 'approve', 'process'
        """
        if not user.is_active:
            raise PermissionError("User is not active")
        
        if action == 'initiate':
            # Staff can initiate
            if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
                return True
            if user.role == 'PHARMACY_OWNER':
                if not hasattr(user, 'owned_pharmacy_brand'):
                    raise PermissionError("Not a pharmacy owner")
                if user.owned_pharmacy_brand.id != pharmacy.id:
                    raise PermissionError("Not your pharmacy")
                return True
            if user.role in ('PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF'):
                from pharmacy.models import PharmacyMembership
                membership = PharmacyMembership.objects.filter(
                    user=user,
                    pharmacy=pharmacy,
                    status='APPROVED'
                ).exists()
                if not membership:
                    raise PermissionError("Not an approved member")
                return True
        
        elif action == 'approve':
            # Only managers/owners can approve
            if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
                return True
            if user.role == 'PHARMACY_OWNER':
                if not hasattr(user, 'owned_pharmacy_brand'):
                    raise PermissionError("Not a pharmacy owner")
                if user.owned_pharmacy_brand.id != pharmacy.id:
                    raise PermissionError("Not your pharmacy")
                return True
            if user.role == 'PHARMACY_MANAGER':
                from pharmacy.models import PharmacyMembership
                membership = PharmacyMembership.objects.filter(
                    user=user,
                    pharmacy=pharmacy,
                    status='APPROVED'
                ).exists()
                if not membership:
                    raise PermissionError("Not an approved member")
                return True
        
        raise PermissionError(f"User cannot {action} returns")
    
    @staticmethod
    @transaction.atomic
    def initiate_return(sale, sale_item, quantity_returned, condition, reason, user, notes=''):
        """
        Staff initiates a customer return.
        
        Args:
            sale: Sale instance
            sale_item: SaleItem instance
            quantity_returned: Quantity being returned
            condition: SELLABLE, DAMAGED, or QUARANTINED
            reason: Reason for return
            user: User initiating
            notes: Optional notes
        
        Returns:
            CustomerReturn: Created return record
        """
        CustomerReturnService.validate_permissions(user, sale.pharmacy, 'initiate')
        
        locked_sale_item = sale_item.__class__.objects.select_for_update().get(pk=sale_item.pk)
        returned_quantity = CustomerReturn.objects.select_for_update().filter(
            sale_item=locked_sale_item,
            status__in=['PENDING_REVIEW', 'APPROVED', 'COMPLETED'],
        ).aggregate(total=Sum('quantity_returned'))['total'] or 0
        remaining_quantity = locked_sale_item.quantity - returned_quantity
        if quantity_returned <= 0:
            raise ValueError("Quantity must be positive")
        if quantity_returned > remaining_quantity:
            raise ValueError(f"Cannot return {quantity_returned}; only {remaining_quantity} units remain returnable")

        allocation = locked_sale_item.batch_allocations_rel.filter(quantity__gte=quantity_returned).first()
        if allocation is None:
            raise ValueError('The requested return spans multiple batches and must be submitted per batch.')
        
        # Create return record
        return_record = CustomerReturn.objects.create(
            pharmacy=sale.pharmacy,
            sale=sale,
            sale_item=sale_item,
            inventory_item=sale_item.inventory_item,
            batch_id=allocation.batch_id,
            quantity_returned=quantity_returned,
            condition=condition,
            reason=reason,
            notes=notes,
            initiated_by=user,
            status='PENDING_REVIEW'
        )
        
        return return_record
    
    @staticmethod
    @transaction.atomic
    def approve_return(return_record, user):
        """
        Manager approves a return.
        
        Args:
            return_record: CustomerReturn instance
            user: Manager user
        
        Returns:
            CustomerReturn: Updated return record
        """
        CustomerReturnService.validate_permissions(user, return_record.pharmacy, 'approve')
        
        return_record.approve(user)
        return return_record
    
    @staticmethod
    @transaction.atomic
    def process_approved_return(return_record, user):
        """
        Process an approved return (update inventory).
        
        Args:
            return_record: CustomerReturn instance (must be APPROVED)
            user: User processing
        
        Returns:
            tuple: (return_record, stock_movements)
        """
        return_record = CustomerReturn.objects.select_for_update().get(pk=return_record.pk)
        return_record = CustomerReturn.objects.select_related(
            'sale', 'sale_item', 'inventory_item', 'batch', 'pharmacy', 'sale__customer'
        ).get(pk=return_record.pk)
        if return_record.status != 'APPROVED':
            raise ValueError(f"Can only process APPROVED returns")
        
        movements = []
        
        # Handle based on condition
        if return_record.condition == 'SELLABLE':
            # Increase sellable stock
            batch = InventoryBatch.objects.select_for_update().get(pk=return_record.batch_id)
            batch.quantity += return_record.quantity_returned
            batch.save(update_fields=['quantity', 'updated_at'])
            
            movement = StockMovement.objects.create(
                movement_type='CUSTOMER_RETURN',
                pharmacy=return_record.pharmacy,
                inventory_item=return_record.inventory_item,
                batch=batch,
                quantity_change=return_record.quantity_returned,
                reason='CUSTOMER_RETURN',
                performed_by=user,
                reference_type='CUSTOMER_RETURN',
                reference_id=return_record.id,
                notes=f"Return approved and restocked"
            )
            movements.append(movement)
            return_record.disposition = 'RETURNED_TO_STOCK'
        
        elif return_record.condition == 'DAMAGED':
            # The sold unit was already removed from stock; record disposition without
            # subtracting it a second time.
            batch = InventoryBatch.objects.select_for_update().get(pk=return_record.batch_id)
            
            movement = StockMovement.objects.create(
                movement_type='DAMAGE',
                pharmacy=return_record.pharmacy,
                inventory_item=return_record.inventory_item,
                batch=batch,
                quantity_change=-return_record.quantity_returned,
                reason='CUSTOMER_RETURN',
                performed_by=user,
                reference_type='CUSTOMER_RETURN',
                reference_id=return_record.id,
                notes=f"Returned damaged item"
            )
            movements.append(movement)
            return_record.disposition = 'MARKED_DAMAGED'
        
        elif return_record.condition == 'QUARANTINED':
            # Place on hold pending decision
            hold = InventoryHold.objects.create(
                batch=return_record.batch,
                pharmacy=return_record.pharmacy,
                inventory_item=return_record.inventory_item,
                quantity=return_record.quantity_returned,
                reason='CUSTOMER_RETURN_INSPECTION',
                initiated_by=user,
                reference_type='CUSTOMER_RETURN',
                reference_id=return_record.id,
            )
            
            # Lock batch and reduce quantity
            batch = InventoryBatch.objects.select_for_update().get(pk=return_record.batch_id)
            batch.quantity -= return_record.quantity_returned
            batch.save(update_fields=['quantity', 'updated_at'])
            
            movement = StockMovement.objects.create(
                movement_type='HOLD',
                pharmacy=return_record.pharmacy,
                inventory_item=return_record.inventory_item,
                batch=batch,
                quantity_change=-return_record.quantity_returned,
                reason='CUSTOMER_RETURN',
                performed_by=user,
                reference_type='INVENTORY_HOLD',
                reference_id=hold.id,
                notes=f"Return placed on hold for inspection"
            )
            movements.append(movement)
            return_record.disposition = 'QUARANTINED_PENDING'
        
        return_record.status = 'COMPLETED'
        return_record.save(update_fields=['status', 'disposition'])

        customer = return_record.sale.customer
        if customer and return_record.sale.payment_method == 'DEBT':
            customer = customer.__class__.objects.select_for_update().get(pk=customer.pk)
            item_value = Decimal(str(return_record.sale_item.unit_price)) * return_record.quantity_returned
            if return_record.sale_item.quantity:
                item_value -= (
                    Decimal(str(return_record.sale_item.line_discount))
                    * return_record.quantity_returned
                    / return_record.sale_item.quantity
                )
            credit_amount = min(max(item_value, Decimal('0.00')), customer.outstanding_balance)
            if credit_amount > Decimal('0.00'):
                CustomerLedgerEntry.objects.create(
                    customer=customer,
                    pharmacy=return_record.pharmacy,
                    sale=return_record.sale,
                    entry_type='RETURN',
                    amount=credit_amount,
                    description=f'Customer return for {return_record.sale.receipt_number}',
                    notes=return_record.notes,
                    balance_after=max(Decimal('0.00'), customer.outstanding_balance - credit_amount),
                    created_by=user,
                )
        
        return return_record, movements


class StockReconciliationService:
    """Service for physical stock counts and reconciliation."""
    
    @staticmethod
    def validate_permissions(user, pharmacy, action='count'):
        """Validate permissions."""
        if not user.is_active:
            raise PermissionError("User is not active")
        
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        if action in ('count', 'approve', 'reconcile'):
            if user.role == 'PHARMACY_OWNER':
                if not hasattr(user, 'owned_pharmacy_brand'):
                    raise PermissionError("Not a pharmacy owner")
                if user.owned_pharmacy_brand.id != pharmacy.id:
                    raise PermissionError("Not your pharmacy")
                return True
            
            if user.role == 'PHARMACY_MANAGER':
                from pharmacy.models import PharmacyMembership
                membership = PharmacyMembership.objects.filter(
                    user=user,
                    pharmacy=pharmacy,
                    status='APPROVED'
                ).exists()
                if not membership:
                    raise PermissionError("Not an approved member")
                return True
        
        raise PermissionError(f"User cannot {action}")
    
    @staticmethod
    @transaction.atomic
    def start_count(inventory_item, batch, user):
        """
        Start a stock count (capture expected quantity).
        
        Args:
            inventory_item: PharmacyInventoryItem
            batch: InventoryBatch
            user: User starting count
        
        Returns:
            StockReconciliation: Created reconciliation record
        """
        StockReconciliationService.validate_permissions(user, inventory_item.pharmacy, 'count')
        
        # Lock and re-read batch to get current quantity
        batch = InventoryBatch.objects.select_for_update().get(pk=batch.pk)
        
        # Create reconciliation record (captures expected quantity now)
        reconciliation = StockReconciliation.objects.create(
            pharmacy=inventory_item.pharmacy,
            inventory_item=inventory_item,
            batch=batch,
            expected_quantity=batch.quantity,
            status='IN_PROGRESS'
        )
        
        return reconciliation
    
    @staticmethod
    @transaction.atomic
    def finalize_count(reconciliation, counted_quantity, user):
        """
        Record the physical count.
        
        Args:
            reconciliation: StockReconciliation instance
            counted_quantity: Physical quantity counted
            user: User performing count
        
        Returns:
            StockReconciliation: Updated reconciliation
        """
        if reconciliation.status != 'IN_PROGRESS':
            raise ValueError(f"Can only finalize IN_PROGRESS counts")
        
        if counted_quantity < 0:
            raise ValueError("Counted quantity must be non-negative")
        
        reconciliation.finalize_count(counted_quantity, user)
        
        return reconciliation
    
    @staticmethod
    @transaction.atomic
    def approve_count(reconciliation, user, notes=''):
        """
        Manager approves the count.
        
        Args:
            reconciliation: StockReconciliation instance
            user: Manager user
            notes: Approval notes
        
        Returns:
            StockReconciliation: Updated reconciliation
        """
        StockReconciliationService.validate_permissions(user, reconciliation.pharmacy, 'approve')
        
        reconciliation.approve(user, notes)
        
        return reconciliation
    
    @staticmethod
    @transaction.atomic
    def reconcile(reconciliation, user):
        """
        Create stock movement to reconcile inventory.
        
        Args:
            reconciliation: StockReconciliation instance (must be APPROVED)
            user: User performing reconciliation
        
        Returns:
            tuple: (reconciliation, movement or None)
        """
        StockReconciliationService.validate_permissions(user, reconciliation.pharmacy, 'reconcile')
        
        if reconciliation.status != 'APPROVED':
            raise ValueError(f"Can only reconcile APPROVED counts")
        
        movement = None
        
        # Create movement if there's a difference
        if reconciliation.difference != 0:
            # Lock batch and update quantity
            batch = InventoryBatch.objects.select_for_update().get(pk=reconciliation.batch_id)
            
            # Double-check current quantity
            # (in case it changed since count - should be impossible but let's be safe)
            if batch.quantity != reconciliation.expected_quantity:
                raise ValueError(
                    f"Batch quantity changed since count started: "
                    f"expected {reconciliation.expected_quantity}, "
                    f"now {batch.quantity}"
                )
            
            # Update batch to counted quantity
            batch.quantity = reconciliation.counted_quantity
            batch.save(update_fields=['quantity', 'updated_at'])
            
            # Create StockMovement
            movement = StockMovement.objects.create(
                movement_type='STOCK_COUNT_CORRECTION',
                pharmacy=reconciliation.pharmacy,
                inventory_item=reconciliation.inventory_item,
                batch=batch,
                quantity_change=reconciliation.difference,
                reason='STOCK_COUNT_CORRECTION',
                performed_by=user,
                reference_type='STOCK_RECONCILIATION',
                reference_id=reconciliation.id,
                notes=f"Stock reconciliation: expected {reconciliation.expected_quantity}, "
                      f"counted {reconciliation.counted_quantity}"
            )
        
        # Mark as reconciled
        reconciliation.reconciled_by = user
        reconciliation.reconciled_at = timezone.now()
        reconciliation.resulting_movement_id = movement.id if movement else None
        reconciliation.status = 'RECONCILED'
        reconciliation.save(update_fields=['reconciled_by', 'reconciled_at', 'resulting_movement_id', 'status'])
        
        return reconciliation, movement
