from datetime import date, timedelta
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from inventory.models import InventoryBatch, PharmacyInventoryItem
from medicine.models import Medicine
from pharmacy.models import PharmacyBrand, PharmacyMembership
from sales.models import StockMovement

from .models import Purchase, PurchaseReceipt, Supplier
from .permissions import CanManageProcurement
from .services import PurchaseService, scoped_purchase_queryset, scoped_supplier_queryset


class ProcurementServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        cls.owner = User.objects.create_user(email='procurement-owner@example.com', password='pass', role='PHARMACY_OWNER')
        cls.other_owner = User.objects.create_user(email='other-owner@example.com', password='pass', role='PHARMACY_OWNER')
        cls.staff = User.objects.create_user(email='procurement-staff@example.com', password='pass', role='PHARMACY_STAFF')
        cls.pharmacy = PharmacyBrand.objects.create(
            owner=cls.owner, legal_name='A Pharmacy Ltd', brand_name='A Pharmacy',
            verification_status='VERIFIED', location=Point(3, 6),
        )
        cls.other_pharmacy = PharmacyBrand.objects.create(
            owner=cls.other_owner, legal_name='B Pharmacy Ltd', brand_name='B Pharmacy',
            verification_status='VERIFIED', location=Point(4, 7),
        )
        cls.medicine = Medicine.objects.create(
            pharmacy=cls.pharmacy, generic_name='Paracetamol', brand_name='Test', strength='500mg',
            dosage_form='TABLET', route='ORAL', created_by=cls.owner,
        )
        cls.inventory_item = PharmacyInventoryItem.objects.create(
            pharmacy=cls.pharmacy, medicine=cls.medicine, selling_price=Decimal('100.00'), created_by=cls.owner,
        )
        cls.supplier = Supplier.objects.create(pharmacy=cls.pharmacy, name='Reliable Pharma', created_by=cls.owner)
        cls.other_supplier = Supplier.objects.create(pharmacy=cls.other_pharmacy, name='Other Pharma', created_by=cls.other_owner)

    def create_purchase(self):
        return PurchaseService.create_purchase(
            user=self.owner,
            pharmacy=self.pharmacy,
            supplier=self.supplier,
            items=[{'medicine': self.medicine, 'quantity_ordered': 10, 'unit_cost': Decimal('25.50')}],
        )

    def test_supplier_and_purchase_isolation(self):
        self.assertEqual(list(scoped_supplier_queryset(self.owner)), [self.supplier])
        self.assertEqual(list(scoped_supplier_queryset(self.other_owner)), [self.other_supplier])
        purchase = self.create_purchase()
        self.assertEqual(list(scoped_purchase_queryset(self.owner)), [purchase])
        self.assertFalse(scoped_purchase_queryset(self.other_owner).filter(pk=purchase.pk).exists())

    def test_purchase_totals_and_partial_then_full_receiving(self):
        purchase = self.create_purchase()
        self.assertEqual(purchase.subtotal, Decimal('255.00'))
        PurchaseService.submit(purchase, self.owner)
        item = purchase.items.get()
        first = PurchaseService.receive(
            purchase=purchase, purchase_item=item, user=self.owner, quantity=4,
            batch_number='BATCH-1', expiry_date=date.today() + timedelta(days=90),
            cost_per_unit=Decimal('25.50'),
        )
        purchase.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(purchase.status, 'PARTIALLY_RECEIVED')
        self.assertEqual(item.received_quantity, 4)
        self.assertEqual(first.batch.quantity, 4)
        self.assertEqual(StockMovement.objects.get(reference_id=purchase.id).movement_type, 'RECEIVE')
        self.assertEqual(StockMovement.objects.get(reference_id=purchase.id).reference_type, 'PURCHASE')

        PurchaseService.receive(
            purchase=purchase, purchase_item=item, user=self.owner, quantity=6,
            batch_number='BATCH-1', expiry_date=date.today() + timedelta(days=90),
            cost_per_unit=Decimal('25.50'),
        )
        purchase.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(purchase.status, 'RECEIVED')
        self.assertEqual(item.received_quantity, 10)
        self.assertEqual(InventoryBatch.objects.get(batch_number='BATCH-1').quantity, 10)
        self.assertEqual(PurchaseReceipt.objects.filter(purchase_item=item).count(), 2)

    def test_over_receiving_does_not_mutate_batch_or_movement(self):
        purchase = self.create_purchase()
        PurchaseService.submit(purchase, self.owner)
        item = purchase.items.get()
        with self.assertRaisesMessage(ValueError, 'exceeds remaining quantity'):
            PurchaseService.receive(
                purchase=purchase, purchase_item=item, user=self.owner, quantity=11,
                batch_number='TOO-MUCH', expiry_date=date.today() + timedelta(days=90),
                cost_per_unit=Decimal('25.50'),
            )
        self.assertFalse(InventoryBatch.objects.filter(batch_number='TOO-MUCH').exists())
        self.assertFalse(StockMovement.objects.filter(reference_id=purchase.id).exists())

    def test_unverified_pharmacy_cannot_create_purchase(self):
        self.pharmacy.verification_status = 'DRAFT'
        self.pharmacy.save(update_fields=('verification_status',))
        with self.assertRaisesMessage(ValueError, 'VERIFIED'):
            self.create_purchase()

    def test_staff_is_not_granted_procurement_write_permission(self):
        request = type('Request', (), {'user': self.staff})()
        self.assertFalse(CanManageProcurement().has_permission(request, None))

    def test_membership_is_required_for_manager_scope(self):
        from django.contrib.auth import get_user_model
        manager = get_user_model().objects.create_user(email='manager@example.com', password='pass', role='PHARMACY_MANAGER')
        self.assertEqual(list(scoped_supplier_queryset(manager)), [])
        PharmacyMembership.objects.create(pharmacy=self.pharmacy, user=manager, role='PHARMACY_MANAGER', status='APPROVED', approved_by=self.owner)
        self.assertEqual(list(scoped_supplier_queryset(manager)), [self.supplier])
