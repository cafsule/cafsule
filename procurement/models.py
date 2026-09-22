import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.db import models

from medicine.models import Medicine
from pharmacy.models import PharmacyBrand
from inventory.models import PharmacyInventoryItem

User = get_user_model()


class Supplier(models.Model):
    STATUS_CHOICES = (('ACTIVE', 'Active'), ('INACTIVE', 'Inactive'))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pharmacy = models.ForeignKey(PharmacyBrand, on_delete=models.CASCADE, related_name='suppliers')
    name = models.CharField(max_length=255)
    contact_person = models.CharField(max_length=255, blank=True, default='')
    phone = models.CharField(max_length=50, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    address = models.TextField(blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    state = models.CharField(max_length=100, blank=True, default='')
    registration_information = models.CharField(max_length=255, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE', db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_suppliers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'procurement_supplier'
        ordering = ('name',)
        constraints = [models.UniqueConstraint(fields=('pharmacy', 'name'), name='unique_supplier_name_per_pharmacy')]
        indexes = [models.Index(fields=('pharmacy', 'status'))]

    def __str__(self):
        return self.name


class Purchase(models.Model):
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('SUBMITTED', 'Submitted'),
        ('PARTIALLY_RECEIVED', 'Partially received'),
        ('RECEIVED', 'Received'),
        ('CANCELLED', 'Cancelled'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pharmacy = models.ForeignKey(PharmacyBrand, on_delete=models.PROTECT, related_name='purchases')
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchases')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='DRAFT', db_index=True)
    notes = models.TextField(blank=True, default='')
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))])
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))])
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_purchases')
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'procurement_purchase'
        ordering = ('-created_at',)
        indexes = [models.Index(fields=('pharmacy', 'status', 'created_at'))]

    def __str__(self):
        return f'Purchase {self.pk}'


class PurchaseItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='items')
    medicine = models.ForeignKey(Medicine, on_delete=models.PROTECT, related_name='purchase_items')
    inventory_item = models.ForeignKey(PharmacyInventoryItem, on_delete=models.PROTECT, related_name='purchase_items')
    quantity_ordered = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    received_quantity = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'procurement_purchase_item'
        constraints = [models.UniqueConstraint(fields=('purchase', 'medicine'), name='unique_medicine_per_purchase')]

    @property
    def subtotal(self):
        return self.unit_cost * self.quantity_ordered

    @property
    def remaining_quantity(self):
        return self.quantity_ordered - self.received_quantity


class PurchaseReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_item = models.ForeignKey(PurchaseItem, on_delete=models.PROTECT, related_name='receipts')
    batch = models.ForeignKey('inventory.InventoryBatch', on_delete=models.PROTECT, related_name='purchase_receipts')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    batch_number = models.CharField(max_length=100)
    expiry_date = models.DateField()
    cost_per_unit = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    received_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='purchase_receipts')
    notes = models.TextField(blank=True, default='')
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'procurement_purchase_receipt'
        ordering = ('-received_at',)
        indexes = [models.Index(fields=('purchase_item', 'received_at'))]
