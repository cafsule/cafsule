"""
Sales and Dispensing Models

This module contains models for pharmacy sales/dispensing operations:
- Customer: The person buying/receiving medicine
- Sale: The overall transaction
- SaleItem: Line items in a sale
- SaleItemBatchAllocation: Tracks which batches are consumed per sale item
- StockMovement: Immutable ledger of all stock changes
"""

import uuid
from decimal import Decimal
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.contrib.auth import get_user_model

from pharmacy.models import PharmacyBrand
from inventory.models import PharmacyInventoryItem, InventoryBatch

User = get_user_model()


class Customer(models.Model):
    """
    Customer/walk-in customer record.
    
    A sale may have:
    - customer = None (anonymous walk-in)
    - customer = Customer instance (registered customer)
    
    This model is simple and does not attempt to be a marketplace account system.
    It is purely for internal pharmacy sales tracking.
    """
    
    CUSTOMER_TYPE_CHOICES = (
        ('WALK_IN', 'Walk-in'),
        ('REGISTERED', 'Registered'),
        ('CORPORATE', 'Corporate'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Basic info (minimal - not a marketplace account)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    
    # Customer type
    customer_type = models.CharField(
        max_length=20,
        choices=CUSTOMER_TYPE_CHOICES,
        default='WALK_IN'
    )
    
    # Pharmacy association
    pharmacy = models.ForeignKey(
        PharmacyBrand,
        on_delete=models.CASCADE,
        related_name='customers',
        help_text="The pharmacy this customer is registered with"
    )
    
    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'sales_customer'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['pharmacy', 'customer_type']),
            models.Index(fields=['phone_number']),
            models.Index(fields=['email']),
        ]
    
    def __str__(self):
        if self.first_name or self.last_name:
            return f"{self.first_name} {self.last_name}".strip()
        return f"Customer {self.customer_type} - {self.phone_number or self.email or self.id}"
    
    def get_display_name(self):
        """Get human-readable customer name"""
        if self.first_name or self.last_name:
            return f"{self.first_name} {self.last_name}".strip()
        if self.phone_number:
            return self.phone_number
        if self.email:
            return self.email
        return f"Walk-in (ID: {self.id})"

    @property
    def total_sales(self):
        """Total value of completed sales for this customer from the ledger when available."""
        ledger_total = self.ledger_entries.filter(entry_type='CREDIT_SALE').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        if self.ledger_entries.exists():
            return Decimal(ledger_total)

        total = self.sales.filter(status='COMPLETED').aggregate(total=Sum('total'))['total'] or Decimal('0.00')
        return Decimal(total)

    @property
    def total_paid(self):
        """Total amount already received from this customer from the ledger when available."""
        ledger_total = self.ledger_entries.filter(entry_type='PAYMENT').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        if self.ledger_entries.exists():
            return Decimal(ledger_total)

        total = self.sales.filter(status='COMPLETED').aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
        return Decimal(total)

    @property
    def outstanding_balance(self):
        """Customer's remaining debt based on authoritative ledger entries when present."""
        debits = self.ledger_entries.filter(entry_type__in=['CREDIT_SALE', 'ADJUSTMENT']).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        credits = self.ledger_entries.filter(entry_type__in=['PAYMENT', 'RETURN', 'VOID']).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        if self.ledger_entries.exists():
            balance = debits - credits
            if balance < Decimal('0.00'):
                return Decimal('0.00')
            return balance

        balance = self.total_sales - self.total_paid
        if balance < Decimal('0.00'):
            return Decimal('0.00')
        return balance

    @property
    def sales_count(self):
        """Number of completed sales for this customer."""
        return self.sales.filter(status='COMPLETED').count()

    @property
    def last_purchase_at(self):
        """Most recent completed sale date for this customer."""
        return self.sales.filter(status='COMPLETED').order_by('-completed_at').values_list('completed_at', flat=True).first()


class CustomerPayment(models.Model):
    """A real customer repayment recorded against a pharmacy customer account."""

    PAYMENT_METHOD_CHOICES = (
        ('CASH', 'Cash'),
        ('POS', 'POS/Card'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('OTHER', 'Other'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='payments',
        help_text='Customer making the repayment'
    )
    pharmacy = models.ForeignKey(
        PharmacyBrand,
        on_delete=models.PROTECT,
        related_name='customer_payments',
        help_text='Pharmacy receiving the payment'
    )
    sale = models.ForeignKey(
        'Sale',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_payments',
        help_text='Optional sale this payment is linked to'
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Repayment amount received'
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default='CASH',
        help_text='Method used for this repayment'
    )
    reference = models.CharField(max_length=120, blank=True, help_text='External reference or transaction ID')
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_payments_recorded',
        help_text='User who recorded the payment'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sales_customer_payment'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', 'created_at']),
            models.Index(fields=['pharmacy', 'created_at']),
        ]

    def __str__(self):
        return f"Payment {self.amount} for {self.customer}"


class CustomerLedgerEntry(models.Model):
    """Authoritative customer account ledger for sales, payments, adjustments and reversals."""

    ENTRY_TYPE_CHOICES = (
        ('CREDIT_SALE', 'Credit Sale'),
        ('PAYMENT', 'Payment'),
        ('RETURN', 'Approved Return'),
        ('ADJUSTMENT', 'Adjustment'),
        ('VOID', 'Voided Sale Reversal'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='ledger_entries',
        help_text='Customer account affected by this transaction'
    )
    pharmacy = models.ForeignKey(
        PharmacyBrand,
        on_delete=models.PROTECT,
        related_name='customer_ledger_entries',
        help_text='Pharmacy owning the account'
    )
    sale = models.ForeignKey(
        'Sale',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ledger_entries',
        help_text='Sale related to this ledger entry'
    )
    payment = models.ForeignKey(
        CustomerPayment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ledger_entries',
        help_text='Payment related to this ledger entry'
    )
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPE_CHOICES, db_index=True)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Absolute amount for the transaction'
    )
    description = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    balance_after = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_ledger_entries',
        help_text='User that created the ledger event'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sales_customer_ledger_entry'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['customer', 'created_at']),
            models.Index(fields=['pharmacy', 'created_at']),
            models.Index(fields=['sale']),
            models.Index(fields=['payment']),
        ]

    def __str__(self):
        return f"{self.customer} {self.entry_type} {self.amount}"


class Sale(models.Model):
    """
    Pharmacy sale/dispensing transaction.
    
    Conceptually:
    - DRAFT: not yet completed, does not consume stock
    - COMPLETED: completed, stock consumed, immutable
    - VOIDED: completed but reversed, original history preserved
    
    A completed sale creates:
    - SaleItems with preserved unit prices
    - SaleItemBatchAllocations (which batches were used)
    - StockMovements (immutable ledger entries)
    
    Completed sales cannot be converted to DRAFT.
    """
    
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('COMPLETED', 'Completed'),
        ('VOIDED', 'Voided'),
    )
    
    PAYMENT_STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('PARTIAL', 'Partial'),
        ('CANCELLED', 'Cancelled'),
    )
    
    PAYMENT_METHOD_CHOICES = (
        ('CASH', 'Cash'),
        ('POS', 'POS/Card'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('OTHER', 'Other'),
        ('DEBT', 'Debt / Credit'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Basic info
    pharmacy = models.ForeignKey(
        PharmacyBrand,
        on_delete=models.PROTECT,
        related_name='sales',
        help_text="The pharmacy making this sale"
    )
    
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales',
        help_text="The customer (optional, for walk-ins)"
    )
    
    # Status and lifecycle
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT',
        db_index=True
    )
    
    # Receipt/Invoice
    receipt_number = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique receipt/invoice number"
    )
    
    # Financial info (all in Decimal)
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Sum of line totals before discount"
    )
    
    discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Sale-level discount"
    )
    
    tax = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Tax amount if applicable"
    )
    
    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Final total = subtotal - discount + tax"
    )
    
    # Payment info
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='PENDING',
        help_text="Payment status (not external transaction verification)"
    )
    
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        blank=True,
        help_text="How the sale was paid"
    )
    
    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Amount actually paid"
    )
    
    # Notes
    notes = models.TextField(
        blank=True,
        help_text="Internal notes about this sale"
    )
    
    # Audit fields
    sold_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_completed',
        help_text="User who completed this sale"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_created',
        help_text="User who created this sale (draft)"
    )
    
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the sale was completed"
    )
    
    voided_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the sale was voided"
    )
    
    voided_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_voided',
        help_text="User who voided this sale"
    )
    
    void_reason = models.TextField(
        blank=True,
        help_text="Reason for voiding"
    )
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'sales_sale'
        ordering = ['-created_at']
        constraints = [
            # Ensure receipt numbers are unique per pharmacy
            models.UniqueConstraint(
                fields=['pharmacy', 'receipt_number'],
                name='unique_receipt_per_pharmacy'
            ),
        ]
        indexes = [
            models.Index(fields=['pharmacy', 'status', 'created_at']),
            models.Index(fields=['pharmacy', 'created_at']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['receipt_number']),
        ]
    
    def __str__(self):
        return f"Sale {self.receipt_number} ({self.get_status_display()})"
    
    @property
    def item_count(self):
        """Number of line items in this sale"""
        return self.items.count()
    
    @property
    def can_be_completed(self):
        """Check if this sale can be completed"""
        if self.status != 'DRAFT':
            return False
        if self.items.count() == 0:
            return False
        return True

    @property
    def remaining_balance(self):
        """Amount still due on this sale."""
        remaining = self.total - self.amount_paid
        if remaining < Decimal('0.00'):
            return Decimal('0.00')
        return remaining

    @property
    def is_credit_sale(self):
        """Whether this sale is not fully settled yet."""
        return self.customer_id is not None and self.total > Decimal('0.00') and self.amount_paid < self.total

    def validate_debt_sale(self):
        """Validate that a debt/credit sale is associated with a real customer."""
        if self.payment_method == 'DEBT':
            if not self.customer_id:
                raise ValueError('A customer is required for credit/debt sales.')
            if self.customer is None:
                raise ValueError('A customer is required for credit/debt sales.')
            if self.customer.pharmacy_id != self.pharmacy_id:
                raise ValueError('Customer does not belong to this pharmacy.')

    def register_customer_ledger_entry(self, *, entry_type, amount, description='', notes='', payment=None, created_by=None):
        """Create an authoritative ledger transaction for customer balances."""
        if not self.customer_id:
            return None

        amount_decimal = Decimal(str(amount))
        if amount_decimal < Decimal('0.00'):
            raise ValueError('Ledger amounts cannot be negative.')

        current_balance = self.customer.outstanding_balance
        new_balance = current_balance + amount_decimal
        if new_balance < Decimal('0.00'):
            new_balance = Decimal('0.00')

        entry = CustomerLedgerEntry.objects.create(
            customer=self.customer,
            pharmacy=self.pharmacy,
            sale=self,
            payment=payment,
            entry_type=entry_type,
            amount=amount_decimal,
            description=description or entry_type.replace('_', ' ').title(),
            notes=notes,
            balance_after=new_balance,
            created_by=created_by,
        )
        return entry

    def validate_customer_payment_request(self, amount):
        """Validate a customer settlement payment against the sale balance."""
        if amount is None:
            raise ValueError('Payment amount is required')
        if amount < Decimal('0.00'):
            raise ValueError('Payment amount must be zero or greater')
        if self.status != 'COMPLETED':
            raise ValueError('Only completed sales can receive customer payments')
        if self.customer is None:
            raise ValueError('A registered customer is required for credit or partial-payment sales')
        if amount > self.remaining_balance:
            raise ValueError('Payment exceeds the remaining sale balance')
        return amount

    def apply_customer_payment(self, amount):
        """Apply a partial or full customer payment against the sale balance."""
        amount = Decimal(str(amount))
        self.validate_customer_payment_request(amount)

        new_amount_paid = self.amount_paid + amount
        self.amount_paid = new_amount_paid

        if new_amount_paid >= self.total:
            self.amount_paid = self.total
            self.payment_status = 'PAID'
        else:
            self.payment_status = 'PARTIAL' if new_amount_paid > Decimal('0.00') else 'PENDING'

        self.save(update_fields=['amount_paid', 'payment_status', 'updated_at'])
        return amount

    def complete(self, user):
        """
        Complete this sale.
        
        This is called by the SaleCompletionService.
        Marks sale as COMPLETED and sets completed_at timestamp.
        Does NOT handle stock reduction - that's done via StockMovements.
        """
        if self.status != 'DRAFT':
            raise ValueError(f"Cannot complete sale with status {self.status}")

        self.validate_debt_sale()

        if self.payment_method == 'DEBT' and self.customer_id:
            self.payment_status = 'PARTIAL' if self.amount_paid < self.total else 'PAID'
            if self.amount_paid <= Decimal('0.00'):
                self.amount_paid = Decimal('0.00')

        self.status = 'COMPLETED'
        self.completed_at = timezone.now()
        self.sold_by = user
        self.save(update_fields=['status', 'completed_at', 'sold_by', 'payment_status', 'amount_paid', 'updated_at'])

        if self.payment_method == 'DEBT' and self.customer_id:
            balance_delta = self.total - self.amount_paid
            if balance_delta > Decimal('0.00'):
                self.register_customer_ledger_entry(
                    entry_type='CREDIT_SALE',
                    amount=balance_delta,
                    description=f'Credit sale {self.receipt_number}',
                    notes='Debt sale recorded to customer account.',
                    created_by=user,
                )
    
    def void(self, user, reason=''):
        """
        Void this completed sale.
        
        This marks the sale as VOIDED. The original sale remains in history.
        A future step can create compensating stock movements.
        """
        if self.status != 'COMPLETED':
            raise ValueError(f"Cannot void sale with status {self.status}")
        
        self.status = 'VOIDED'
        self.voided_at = timezone.now()
        self.voided_by = user
        self.void_reason = reason
        self.save(update_fields=['status', 'voided_at', 'voided_by', 'void_reason', 'updated_at'])


class SaleItem(models.Model):
    """
    Line item in a sale.
    
    Represents one medicine/product sold in the sale.
    
    Important: unit_price is stored to preserve historical transaction prices.
    If inventory price changes tomorrow, the sale still shows today's price.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relationship to sale
    sale = models.ForeignKey(
        Sale,
        on_delete=models.CASCADE,
        related_name='items',
        help_text="The sale this item belongs to"
    )
    
    # Product reference
    inventory_item = models.ForeignKey(
        PharmacyInventoryItem,
        on_delete=models.PROTECT,
        related_name='sale_items',
        help_text="The inventory item being sold"
    )
    
    # Quantity and pricing (transaction-time price preserved)
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Quantity sold"
    )
    
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Unit price at time of sale (preserved for history)"
    )
    
    line_discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Discount on this line item"
    )
    
    line_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Total for this line = (quantity * unit_price) - line_discount"
    )
    
    # Batch allocation
    # Multiple batches can be consumed for one SaleItem
    # See SaleItemBatchAllocation for actual batch usage
    
    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'sales_sale_item'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['sale', 'created_at']),
            models.Index(fields=['inventory_item']),
        ]
    
    def __str__(self):
        return f"SaleItem {self.inventory_item} x {self.quantity} in {self.sale.receipt_number}"
    
    @property
    def batch_allocations(self):
        """Get batch allocations for this item (convenience property)"""
        return self.batch_allocations_rel.all()


class SaleItemBatchAllocation(models.Model):
    """
    Tracks which batches were consumed for a sale item.
    
    One SaleItem may consume multiple batches.
    
    Example:
    - SaleItem: 70 units of Panadol
    - Batch A (expires 2027): 50 units
    - Batch B (expires 2028): 20 units
    
    This allows exact traceability: sale → item → batches → stock movements
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    sale_item = models.ForeignKey(
        SaleItem,
        on_delete=models.CASCADE,
        related_name='batch_allocations_rel',
        help_text="The sale item being allocated"
    )
    
    batch = models.ForeignKey(
        InventoryBatch,
        on_delete=models.PROTECT,
        related_name='sale_allocations',
        help_text="The batch allocated"
    )
    
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Quantity consumed from this batch"
    )
    
    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'sales_sale_item_batch_allocation'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['sale_item']),
            models.Index(fields=['batch']),
        ]
    
    def __str__(self):
        return f"Allocation: {self.quantity} units from {self.batch.batch_number} to {self.sale_item}"


class StockMovement(models.Model):
    """
    Immutable ledger entry for all stock changes.
    
    Every stock change is recorded here:
    - SALE: stock consumed by a sale
    - VOID: compensating movement from sale void
    - RECEIVE: stock received from supplier (purchase order flow)
    - ADJUSTMENT: manual inventory adjustment
    - DAMAGE: damaged stock write-off
    - EXPIRED: expired stock write-off
    - LOSS: missing/lost stock
    - CUSTOMER_RETURN: customer return (can be positive or negative)
    - STOCK_COUNT_CORRECTION: reconciliation adjustment
    - HOLD: stock placed on hold/quarantine
    - RELEASE: stock released from hold/quarantine
    
    This is the authoritative audit trail for stock changes.
    Never delete or edit these records.
    """
    
    MOVEMENT_TYPE_CHOICES = (
        ('SALE', 'Sale'),
        ('VOID', 'Void/Reversal'),
        ('RECEIVE', 'Receive from Supplier'),
        ('ADJUSTMENT', 'Manual Adjustment'),
        ('DAMAGE', 'Damage'),
        ('EXPIRED', 'Expired Stock Write-off'),
        ('LOSS', 'Loss/Missing Stock'),
        ('CUSTOMER_RETURN', 'Customer Return'),
        ('STOCK_COUNT_CORRECTION', 'Stock Count Correction'),
        ('HOLD', 'Stock Hold/Quarantine'),
        ('RELEASE', 'Hold Release'),
    )
    
    REASON_CHOICES = (
        # For ADJUSTMENT
        ('STOCK_COUNT_CORRECTION', 'Physical Count Correction'),
        ('DATA_ENTRY_ERROR', 'Data Entry Error'),
        ('FOUND', 'Lost Item Found'),
        ('ADJUSTMENT_OTHER', 'Other Adjustment'),
        
        # For DAMAGE
        ('DAMAGED_IN_STORAGE', 'Damaged in Storage'),
        ('DAMAGED_IN_DELIVERY', 'Damaged During Delivery'),
        ('QUALITY_ISSUE', 'Quality Issue'),
        ('PACKAGING_COMPROMISED', 'Packaging Compromised'),
        ('DAMAGE_OTHER', 'Other Damage'),
        
        # For EXPIRED
        ('NATURAL_EXPIRY', 'Natural Expiry'),
        ('DAMAGED_EXPIRY', 'Damaged - Also Expired'),
        ('RECALLED', 'Product Recalled'),
        
        # For LOSS
        ('MISSING_INVENTORY', 'Missing from Inventory'),
        ('SUSPECTED_THEFT', 'Suspected Theft'),
        ('UNKNOWN_LOSS', 'Unknown Loss'),
        
        # For all
        ('OTHER', 'Other'),
    )
    
    REFERENCE_TYPE_CHOICES = (
        ('PURCHASE', 'Purchase'),
        ('CUSTOMER_RETURN', 'Customer Return'),
        ('STOCK_RECONCILIATION', 'Stock Reconciliation'),
        ('INVENTORY_HOLD', 'Inventory Hold'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Movement identification
    movement_type = models.CharField(
        max_length=30,
        choices=MOVEMENT_TYPE_CHOICES,
        db_index=True,
        help_text="Type of stock movement"
    )
    
    # Ownership
    pharmacy = models.ForeignKey(
        PharmacyBrand,
        on_delete=models.PROTECT,
        related_name='stock_movements',
        help_text="The pharmacy's stock"
    )
    
    # Product reference
    inventory_item = models.ForeignKey(
        PharmacyInventoryItem,
        on_delete=models.PROTECT,
        related_name='stock_movements',
        help_text="The inventory item"
    )
    
    batch = models.ForeignKey(
        InventoryBatch,
        on_delete=models.PROTECT,
        related_name='stock_movements',
        help_text="The specific batch"
    )
    
    # Quantity change
    quantity_change = models.IntegerField(
        help_text="Quantity change (negative for sales/damage/loss, positive for returns/receipts)"
    )
    
    # Reason (why the movement happened)
    reason = models.CharField(
        max_length=50,
        choices=REASON_CHOICES,
        blank=True,
        help_text="Reason for the movement"
    )
    
    # References to parent transactions
    reference_type = models.CharField(
        max_length=50,
        choices=REFERENCE_TYPE_CHOICES,
        null=True,
        blank=True,
        help_text="Type of parent transaction"
    )
    
    reference_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="ID of parent transaction (CustomerReturn, StockReconciliation, InventoryHold)"
    )
    
    # Sale references (for SALE and VOID movements)
    sale = models.ForeignKey(
        Sale,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='stock_movements',
        help_text="Sale reference if this is a SALE movement"
    )
    
    sale_item = models.ForeignKey(
        SaleItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='stock_movements',
        help_text="SaleItem reference if this is a SALE movement"
    )
    
    # Actor
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_movements',
        help_text="User who initiated this movement"
    )
    
    # Notes
    notes = models.TextField(
        blank=True,
        help_text="Additional context about this movement"
    )
    
    # Immutable timestamp
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'sales_stock_movement'
        ordering = ['-created_at']
        # Movements are immutable - only read operations
        constraints = [
            # Ensure SALE movements reference a sale
            models.CheckConstraint(
                check=models.Q(movement_type='SALE', sale__isnull=False) |
                      models.Q(movement_type__in=['RECEIVE', 'ADJUSTMENT', 'VOID', 'DAMAGE', 'EXPIRED', 'LOSS', 'CUSTOMER_RETURN', 'STOCK_COUNT_CORRECTION', 'HOLD', 'RELEASE']),
                name='sale_movement_has_sale_reference'
            ),
            # Quantity must not be zero
            models.CheckConstraint(
                check=~models.Q(quantity_change=0),
                name='movement_quantity_nonzero'
            ),
        ]
        indexes = [
            models.Index(fields=['pharmacy', 'created_at']),
            models.Index(fields=['pharmacy', 'movement_type', 'created_at']),
            models.Index(fields=['inventory_item', 'created_at']),
            models.Index(fields=['batch', 'created_at']),
            models.Index(fields=['sale']),
            models.Index(fields=['movement_type', 'created_at']),
            models.Index(fields=['reference_type', 'reference_id']),
        ]
    
    def __str__(self):
        reason_str = f" ({self.get_reason_display()})" if self.reason else ""
        return f"{self.get_movement_type_display()} {self.quantity_change} units{reason_str}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("Stock movements are immutable")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Stock movements are immutable")
    
    @classmethod
    def create_sale_movement(cls, sale, sale_item, batch, quantity, user):
        """
        Create a SALE stock movement.
        
        Called by SaleCompletionService during sale completion.
        Quantity should be negative (stock consumed).
        """
        return cls.objects.create(
            movement_type='SALE',
            pharmacy=sale.pharmacy,
            inventory_item=sale_item.inventory_item,
            batch=batch,
            quantity_change=-quantity,  # Negative for sales
            sale=sale,
            sale_item=sale_item,
            performed_by=user,
        )

    @classmethod
    def create_void_movement(cls, sale, sale_item, batch, quantity, user, notes=''):
        """Create a positive immutable movement that reverses a sale allocation."""
        return cls.objects.create(
            movement_type='VOID',
            pharmacy=sale.pharmacy,
            inventory_item=sale_item.inventory_item,
            batch=batch,
            quantity_change=quantity,
            sale=sale,
            sale_item=sale_item,
            performed_by=user,
            notes=notes,
        )
