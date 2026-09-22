import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from pharmacy.models import PharmacyBrand

User = get_user_model()


class Expense(models.Model):
    CATEGORY_CHOICES = (
        ('RENT', 'Rent'),
        ('UTILITIES', 'Utilities'),
        ('STAFF', 'Staff'),
        ('TRANSPORT', 'Transport'),
        ('MAINTENANCE', 'Maintenance'),
        ('BANK_FEES', 'Bank Fees'),
        ('SOFTWARE', 'Software'),
        ('MARKETING', 'Marketing'),
        ('CLEANING', 'Cleaning'),
        ('OTHER', 'Other'),
    )

    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )

    PAYMENT_METHOD_CHOICES = (
        ('CASH', 'Cash'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('POS', 'POS/Card'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('OTHER', 'Other'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pharmacy = models.ForeignKey(PharmacyBrand, on_delete=models.PROTECT, related_name='expenses')
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    expense_date = models.DateField(default=timezone.now)
    description = models.CharField(max_length=255)
    reference = models.CharField(max_length=120, blank=True, default='')
    payment_method = models.CharField(max_length=25, choices=PAYMENT_METHOD_CHOICES, default='CASH', blank=True)
    notes = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_expenses')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_expenses')
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'expense'
        ordering = ('-expense_date', '-created_at')
        indexes = [
            models.Index(fields=['pharmacy', 'expense_date']),
            models.Index(fields=['pharmacy', 'category']),
            models.Index(fields=['status', 'expense_date']),
        ]

    def __str__(self):
        return f'{self.category} - {self.amount}'

    def approve(self, user):
        if self.status == 'REJECTED':
            raise ValueError('Rejected expenses cannot be approved without re-entry.')
        self.status = 'APPROVED'
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

    def reject(self, user, reason=''):
        if self.status == 'APPROVED':
            raise ValueError('Approved expenses cannot be rejected without a correction entry.')
        self.status = 'REJECTED'
        self.approved_by = user
        self.approved_at = timezone.now()
        self.notes = f'{self.notes}\n{reason}'.strip()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'notes', 'updated_at'])
