"""
Pharmacy Inventory Models

This module contains pharmacy-specific inventory management.
Separates:
- Canonical medicine definitions (medicine app)
- Pharmacy inventory (this app)
- Stock batches with expiry tracking
- Publication/visibility state
"""

import uuid
from django.db import models, transaction
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.contrib.auth import get_user_model
from decimal import Decimal

from pharmacy.models import PharmacyBrand
from medicine.models import Medicine

User = get_user_model()


class PharmacyInventoryItem(models.Model):
    """
    Pharmacy-specific inventory record.
    
    Links a PharmacyBrand to a Medicine and tracks:
    - Whether the pharmacy carries this product
    - Selling price (pharmacy-specific)
    - Publication status (whether visible in Smart Medicine Finder)
    - Inventory status (ACTIVE/INACTIVE)
    
    Stock quantities are tracked in InventoryBatch.
    """
    
    STATUS_CHOICES = (
        ('ACTIVE', 'Active'),
        ('INACTIVE', 'Inactive'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Ownership
    pharmacy = models.ForeignKey(
        PharmacyBrand,
        on_delete=models.CASCADE,
        related_name='inventory_items',
        help_text="The pharmacy that carries this item"
    )
    
    # Product reference
    medicine = models.ForeignKey(
        Medicine,
        on_delete=models.PROTECT,  # Don't allow medicine deletion if in use
        related_name='pharmacy_inventory',
        help_text="The medicine/product definition"
    )
    
    # Pharmacy-specific data
    selling_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Selling price in NGN"
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='ACTIVE',
        db_index=True
    )
    
    # Publication (separate from status - visibility/searchability)
    is_published = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this item is published to Smart Medicine Finder"
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this item was published"
    )
    published_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='published_inventory_items',
        help_text="User who published this item"
    )
    unpublished_at = models.DateTimeField(null=True, blank=True)
    unpublished_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='unpublished_inventory_items',
        help_text="User who unpublished this item"
    )
    
    reorder_level = models.PositiveIntegerField(
        default=0,
        help_text="Minimum sellable quantity before this item is low stock"
    )
    
    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_inventory_items'
    )
    
    class Meta:
        db_table = 'pharmacy_inventory_item'
        ordering = ['pharmacy', 'medicine']
        # Prevent duplicate inventory for same pharmacy + medicine
        unique_together = [('pharmacy', 'medicine')]
        indexes = [
            models.Index(fields=['pharmacy', 'status']),
            models.Index(fields=['pharmacy', 'is_published']),
            models.Index(fields=['is_published', 'status']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.pharmacy.brand_name} - {self.medicine.generic_name} {self.medicine.strength}"
    
    @property
    def total_quantity(self):
        """Calculate total quantity from all non-expired batches"""
        from django.db.models import Sum
        from django.utils import timezone
        
        result = InventoryBatch.objects.filter(
            inventory_item=self,
            expiry_date__gt=timezone.now().date()
        ).aggregate(total=Sum('quantity'))
        return result['total'] or 0
    
    @property
    def has_expired_stock(self):
        """Check if any batches are expired"""
        from django.utils import timezone
        return InventoryBatch.objects.filter(
            inventory_item=self,
            expiry_date__lte=timezone.now().date()
        ).exists()
    
    def can_publish(self):
        """
        Check if this inventory item can be published.
        
        Requirements:
        - Pharmacy must be VERIFIED
        - Item must have positive price
        - Item must be ACTIVE
        - Stock availability is derived separately for public discovery
        """
        if self.pharmacy.verification_status != 'VERIFIED':
            return False, f"Pharmacy is {self.pharmacy.get_verification_status_display()}, not VERIFIED"
        
        if self.selling_price <= 0:
            return False, "Selling price must be greater than 0"
        
        if self.status != 'ACTIVE':
            return False, f"Inventory item is {self.get_status_display()}, not ACTIVE"
        
        return True, "Can publish"
    
    @transaction.atomic
    def publish(self, user):
        """Publish this inventory item"""
        can_publish, reason = self.can_publish()
        if not can_publish:
            raise ValueError(reason)
        
        self.is_published = True
        self.published_at = timezone.now()
        self.published_by = user
        self.unpublished_at = None
        self.unpublished_by = None
        self.save(update_fields=[
            'is_published', 'published_at', 'published_by',
            'unpublished_at', 'unpublished_by', 'updated_at'
        ])
    
    @transaction.atomic
    def unpublish(self, user=None):
        """Unpublish this inventory item"""
        self.is_published = False
        self.published_at = None
        self.published_by = None
        self.unpublished_at = timezone.now()
        self.unpublished_by = user
        self.save(update_fields=['is_published', 'unpublished_at', 'unpublished_by', 'updated_at'])


class InventoryBatch(models.Model):
    """
    Specific stock batch for an inventory item.
    
    Tracks:
    - Batch identifier
    - Quantity
    - Expiry date
    - Cost information
    
    Multiple batches can exist for the same inventory item.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relationship
    inventory_item = models.ForeignKey(
        PharmacyInventoryItem,
        on_delete=models.CASCADE,
        related_name='batches',
        help_text="The inventory item this batch belongs to"
    )
    
    # Batch identification
    batch_number = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Batch/lot number from supplier"
    )
    
    # Stock information
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
        help_text="Available quantity"
    )
    
    # Expiry tracking
    expiry_date = models.DateField(
        db_index=True,
        help_text="Batch expiry date"
    )
    
    # Cost (for internal tracking, not in scope for this task)
    cost_per_unit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        null=True,
        blank=True,
        help_text="Cost per unit (supplier cost)"
    )
    
    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'inventory_batch'
        ordering = ['inventory_item', 'expiry_date']
        # Prevent duplicate batches for same item
        unique_together = [('inventory_item', 'batch_number')]
        constraints = [
            # Ensure quantity never negative
            models.CheckConstraint(
                check=models.Q(quantity__gte=0),
                name='batch_quantity_non_negative'
            ),
        ]
        indexes = [
            models.Index(fields=['inventory_item', 'expiry_date']),
            models.Index(fields=['expiry_date']),
        ]
    
    def __str__(self):
        return f"{self.inventory_item} - Batch {self.batch_number}"
    
    @property
    def is_expired(self):
        """Check if this batch is expired"""
        return self.expiry_date <= timezone.now().date()
    
    @property
    def days_until_expiry(self):
        """Calculate days until expiry (negative if expired)"""
        from datetime import date
        return (self.expiry_date - date.today()).days


class CustomerReturn(models.Model):
    """
    Customer return transaction.
    
    Tracks when a customer returns a purchased item.
    Returns go through an approval workflow before inventory is affected.
    
    Workflow:
    - PENDING_REVIEW: Staff initiates return
    - APPROVED: Manager approves the return
    - REJECTED: Manager rejects (return not accepted)
    - COMPLETED: Return processed (inventory action taken)
    - CANCELLED: Return cancelled
    
    The return can result in:
    - Sellable stock increase
    - Quarantine hold
    - Damage write-off
    depending on condition and subsequent inspection.
    """
    
    CONDITION_CHOICES = (
        ('SELLABLE', 'Sellable - No Issues'),
        ('DAMAGED', 'Damaged - Cannot Resell'),
        ('QUARANTINED', 'Quarantined - Pending Inspection'),
    )
    
    STATUS_CHOICES = (
        ('PENDING_REVIEW', 'Pending Review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    )
    
    DISPOSITION_CHOICES = (
        ('RETURNED_TO_STOCK', 'Returned to Sellable Stock'),
        ('QUARANTINED_PENDING', 'Quarantined Pending Decision'),
        ('MARKED_DAMAGED', 'Marked as Damaged'),
        ('DISPOSED', 'Disposed'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Links to original sale
    pharmacy = models.ForeignKey(
        PharmacyBrand,
        on_delete=models.PROTECT,
        related_name='customer_returns',
        help_text="The pharmacy processing this return"
    )
    
    sale = models.ForeignKey(
        'sales.Sale',
        on_delete=models.PROTECT,
        related_name='customer_returns',
        help_text="The original sale"
    )
    
    sale_item = models.ForeignKey(
        'sales.SaleItem',
        on_delete=models.PROTECT,
        related_name='returns',
        help_text="The original sale item"
    )
    
    inventory_item = models.ForeignKey(
        PharmacyInventoryItem,
        on_delete=models.PROTECT,
        related_name='customer_returns',
        help_text="The inventory item being returned"
    )
    
    batch = models.ForeignKey(
        InventoryBatch,
        on_delete=models.PROTECT,
        related_name='customer_returns',
        help_text="The batch being returned"
    )
    
    # Return details
    quantity_returned = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Quantity being returned"
    )
    
    condition = models.CharField(
        max_length=20,
        choices=CONDITION_CHOICES,
        help_text="Condition of returned item"
    )
    
    reason = models.CharField(
        max_length=100,
        blank=True,
        help_text="Customer's reason for return (CUSTOMER_COMPLAINT, DEFECTIVE, QUALITY_ISSUE, etc.)"
    )
    
    notes = models.TextField(
        blank=True,
        help_text="Additional notes about this return"
    )
    
    # Workflow state
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING_REVIEW',
        db_index=True
    )
    
    disposition = models.CharField(
        max_length=30,
        choices=DISPOSITION_CHOICES,
        null=True,
        blank=True,
        help_text="How the return was disposed"
    )
    
    # Actors
    initiated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='initiated_returns',
        help_text="Staff member who initiated the return"
    )
    
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_returns',
        help_text="Manager who approved/rejected the return"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    # Reference to resulting stock movement(s)
    # Query via StockMovement.reference_type='CUSTOMER_RETURN', reference_id=this.id
    
    class Meta:
        db_table = 'inventory_customer_return'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['pharmacy', 'created_at']),
            models.Index(fields=['pharmacy', 'status']),
            models.Index(fields=['sale', 'created_at']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['inventory_item', 'created_at']),
        ]
    
    def __str__(self):
        return f"Return {self.id} - {self.quantity_returned} units ({self.get_status_display()})"
    
    def approve(self, user):
        """Mark return as approved"""
        if self.status != 'PENDING_REVIEW':
            raise ValueError(f"Cannot approve return with status {self.status}")
        
        self.status = 'APPROVED'
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    
    def reject(self, user):
        """Reject this return"""
        if self.status != 'PENDING_REVIEW':
            raise ValueError(f"Cannot reject return with status {self.status}")
        
        self.status = 'REJECTED'
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    
    def get_related_stock_movements(self):
        """Get all StockMovements created for this return"""
        from sales.models import StockMovement
        return StockMovement.objects.filter(
            reference_type='CUSTOMER_RETURN',
            reference_id=self.id
        )


class InventoryHold(models.Model):
    """
    Inventory hold/quarantine record.
    
    Tracks stock that has been placed on hold (quarantine).
    This is separate from sellable inventory.
    
    When stock is quarantined:
    - InventoryBatch.quantity is decreased (stock removed from available)
    - InventoryHold record tracks what's on hold and why
    - StockMovement(HOLD) records the event
    
    When hold is resolved:
    - Manager decides: RETURN_TO_STOCK, MARK_DAMAGED, MARK_EXPIRED, WRITE_OFF
    - Appropriate StockMovement is created
    - InventoryHold.status updated
    
    This allows partial quarantine of a batch.
    
    Example:
    - Batch quantity = 100
    - 3 units quarantined (InventoryHold created)
    - Batch quantity becomes 97 (sold from available)
    - Later: 2 units released (RETURN_TO_STOCK)
    - 1 unit marked as damage (MARK_DAMAGED)
    """
    
    STATUS_CHOICES = (
        ('ON_HOLD', 'On Hold'),
        ('RESOLVED', 'Resolved'),
        ('CANCELLED', 'Cancelled'),
    )
    
    RESOLUTION_CHOICES = (
        ('RETURN_TO_STOCK', 'Return to Sellable Stock'),
        ('MARK_DAMAGED', 'Mark as Damaged'),
        ('MARK_EXPIRED', 'Mark as Expired'),
        ('WRITE_OFF', 'Write Off'),
        ('OTHER', 'Other'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Which batch is on hold
    batch = models.ForeignKey(
        InventoryBatch,
        on_delete=models.PROTECT,
        related_name='holds',
        help_text="The batch on hold"
    )
    
    pharmacy = models.ForeignKey(
        PharmacyBrand,
        on_delete=models.PROTECT,
        related_name='inventory_holds',
        help_text="The pharmacy"
    )
    
    inventory_item = models.ForeignKey(
        PharmacyInventoryItem,
        on_delete=models.PROTECT,
        related_name='holds',
        help_text="The inventory item"
    )
    
    # Hold details
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Quantity on hold"
    )
    
    reason = models.CharField(
        max_length=100,
        help_text="Reason for hold (CUSTOMER_RETURN, QUALITY_ISSUE, INSPECTION_PENDING, etc.)"
    )
    
    notes = models.TextField(
        blank=True,
        help_text="Additional notes"
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='ON_HOLD',
        db_index=True
    )
    
    resolution = models.CharField(
        max_length=30,
        choices=RESOLUTION_CHOICES,
        null=True,
        blank=True,
        help_text="How the hold was resolved"
    )
    
    # Actors
    initiated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='initiated_holds',
        help_text="User who initiated the hold"
    )
    
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_holds',
        help_text="User who resolved the hold"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    # Link to parent transaction (e.g., CustomerReturn)
    reference_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Type of parent transaction (CUSTOMER_RETURN, etc.)"
    )
    reference_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="ID of parent transaction"
    )
    
    class Meta:
        db_table = 'inventory_hold'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['batch', 'status']),
            models.Index(fields=['pharmacy', 'created_at']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['reference_type', 'reference_id']),
        ]
    
    def __str__(self):
        return f"Hold {self.id} - {self.quantity} units ({self.get_status_display()})"
    
    def resolve(self, user, resolution, release_quantity):
        """
        Resolve the hold.
        
        Args:
            user: User resolving the hold
            resolution: How it was resolved (RETURN_TO_STOCK, MARK_DAMAGED, etc.)
            release_quantity: How many units to release/action
        """
        if release_quantity > self.quantity:
            raise ValueError(f"Cannot release {release_quantity} from hold of {self.quantity}")
        
        if release_quantity <= 0:
            raise ValueError("Release quantity must be > 0")
        
        self.resolution = resolution
        self.resolved_by = user
        self.resolved_at = timezone.now()
        
        if release_quantity == self.quantity:
            self.status = 'RESOLVED'
        
        self.save(update_fields=['resolution', 'resolved_by', 'resolved_at', 'status'])


class StockReconciliation(models.Model):
    """
    Physical stock count and reconciliation record.
    
    Workflow:
    1. Staff starts count (captures expected quantity)
    2. Staff performs physical count
    3. Manager approves the count
    4. Authorized user reconciles (creates movement to adjust batch)
    
    This prevents:
    - Manipulating expected quantity mid-count
    - Arbitrary quantity changes
    - Audit trail gaps
    """
    
    STATUS_CHOICES = (
        ('IN_PROGRESS', 'Count In Progress'),
        ('PENDING_APPROVAL', 'Pending Manager Approval'),
        ('APPROVED', 'Approved'),
        ('RECONCILED', 'Reconciled'),
        ('CANCELLED', 'Cancelled'),
    )
    
    DISCREPANCY_TYPE_CHOICES = (
        ('NO_DISCREPANCY', 'Quantity Matches'),
        ('SHORTAGE', 'Shortage - Fewer Units'),
        ('OVERAGE', 'Overage - Extra Units'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # What is being counted
    pharmacy = models.ForeignKey(
        PharmacyBrand,
        on_delete=models.PROTECT,
        related_name='stock_reconciliations',
        help_text="The pharmacy"
    )
    
    inventory_item = models.ForeignKey(
        PharmacyInventoryItem,
        on_delete=models.PROTECT,
        related_name='reconciliations',
        help_text="The inventory item"
    )
    
    batch = models.ForeignKey(
        InventoryBatch,
        on_delete=models.PROTECT,
        related_name='reconciliations',
        help_text="The batch being counted"
    )
    
    # Count snapshot (captured at start, IMMUTABLE)
    expected_quantity = models.PositiveIntegerField(
        help_text="Quantity per system at count start"
    )
    
    expected_quantity_captured_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When expected quantity was captured"
    )
    
    # Physical count
    counted_quantity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Physical quantity counted"
    )
    
    counted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the count was performed"
    )
    
    counted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='performed_counts',
        help_text="User who performed the count"
    )
    
    # Difference (computed after count)
    difference = models.IntegerField(
        null=True,
        blank=True,
        help_text="counted_quantity - expected_quantity"
    )
    
    discrepancy_type = models.CharField(
        max_length=20,
        choices=DISCREPANCY_TYPE_CHOICES,
        null=True,
        blank=True,
        help_text="Type of discrepancy"
    )
    
    # Investigation
    reason_for_discrepancy = models.CharField(
        max_length=100,
        blank=True,
        help_text="Reason for discrepancy (INVENTORY_ERROR, THEFT, DATA_ENTRY, etc.)"
    )
    
    notes = models.TextField(
        blank=True,
        help_text="Investigation notes"
    )
    
    # Workflow state
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='IN_PROGRESS',
        db_index=True
    )
    
    # Approval
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_reconciliations',
        help_text="Manager who approved the count"
    )
    
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the count was approved"
    )
    
    approval_notes = models.TextField(
        blank=True,
        help_text="Approval notes"
    )
    
    # Reconciliation (final step)
    reconciled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='performed_reconciliations',
        help_text="User who performed reconciliation"
    )
    
    reconciled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When reconciliation was completed"
    )
    
    resulting_movement_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="ID of resulting StockMovement (if any)"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'inventory_stock_reconciliation'
        ordering = ['-created_at']
        constraints = [
            # Once counted, can't have null difference
            models.CheckConstraint(
                check=models.Q(counted_quantity__isnull=True) | models.Q(difference__isnull=False),
                name='count_implies_difference'
            ),
        ]
        indexes = [
            models.Index(fields=['pharmacy', 'created_at']),
            models.Index(fields=['pharmacy', 'status']),
            models.Index(fields=['batch', 'created_at']),
            models.Index(fields=['status', 'created_at']),
        ]
    
    def __str__(self):
        return f"Reconciliation {self.id} - {self.batch} ({self.get_status_display()})"
    
    def finalize_count(self, counted_quantity, user):
        """Record the physical count"""
        if self.status != 'IN_PROGRESS':
            raise ValueError(f"Can only finalize IN_PROGRESS counts, current status: {self.status}")
        
        self.counted_quantity = counted_quantity
        self.counted_at = timezone.now()
        self.counted_by = user
        self.difference = counted_quantity - self.expected_quantity
        
        if self.difference == 0:
            self.discrepancy_type = 'NO_DISCREPANCY'
        elif self.difference > 0:
            self.discrepancy_type = 'OVERAGE'
        else:
            self.discrepancy_type = 'SHORTAGE'
        
        self.status = 'PENDING_APPROVAL'
        self.save(update_fields=[
            'counted_quantity', 'counted_at', 'counted_by', 
            'difference', 'discrepancy_type', 'status'
        ])
    
    def approve(self, user, notes=''):
        """Manager approves the count"""
        if self.status != 'PENDING_APPROVAL':
            raise ValueError(f"Can only approve PENDING_APPROVAL counts, current status: {self.status}")
        
        self.approved_by = user
        self.approved_at = timezone.now()
        self.approval_notes = notes
        self.status = 'APPROVED'
        self.save(update_fields=['approved_by', 'approved_at', 'approval_notes', 'status'])
