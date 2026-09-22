from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from inventory.models import PharmacyInventoryItem, InventoryBatch
from medicine.models import Medicine
from pharmacy.models import PharmacyBrand, PharmacyMembership
from sales.models import Sale, SaleItem, StockMovement

User = get_user_model()


class ReportsAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.owner = User.objects.create_user(
            email='owner@pharmacy.test',
            password='Testpass123!',
            first_name='Alice',
            last_name='Owner',
            role='PHARMACY_OWNER',
            is_verified=True,
            is_active=True,
            account_status='ACTIVE',
            is_approved=True,
        )
        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Alpha Pharmacy',
            brand_name='Alpha Pharmacy',
            verification_status='VERIFIED',
        )

        self.other_owner = User.objects.create_user(
            email='owner2@pharmacy.test',
            password='Testpass123!',
            first_name='Bob',
            last_name='Owner',
            role='PHARMACY_OWNER',
            is_verified=True,
            is_active=True,
            account_status='ACTIVE',
            is_approved=True,
        )
        self.other_pharmacy = PharmacyBrand.objects.create(
            owner=self.other_owner,
            legal_name='Beta Pharmacy',
            brand_name='Beta Pharmacy',
            verification_status='VERIFIED',
        )

        self.medicine = Medicine.objects.create(
            generic_name='Paracetamol',
            strength='500mg',
            dosage_form='TABLET',
        )

        self.inventory = PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy,
            medicine=self.medicine,
            selling_price=Decimal('150.00'),
            status='ACTIVE',
        )
        self.batch = InventoryBatch.objects.create(
            inventory_item=self.inventory,
            batch_number='BATCH-001',
            quantity=40,
            expiry_date=timezone.now().date() + timezone.timedelta(days=20),
            cost_per_unit=Decimal('60.00'),
        )
        self.other_inventory = PharmacyInventoryItem.objects.create(
            pharmacy=self.other_pharmacy,
            medicine=self.medicine,
            selling_price=Decimal('160.00'),
            status='ACTIVE',
        )

        self.manager = User.objects.create_user(
            email='manager@pharmacy.test',
            password='Testpass123!',
            first_name='Mia',
            last_name='Manager',
            role='PHARMACY_MANAGER',
            is_verified=True,
            is_active=True,
            account_status='ACTIVE',
            is_approved=True,
        )
        PharmacyMembership.objects.create(
            user=self.manager,
            pharmacy=self.pharmacy,
            role='PHARMACY_MANAGER',
            status='APPROVED',
        )

    def _create_completed_sale(self, total=Decimal('1000.00'), payment_method='CASH', quantity=5):
        sale = Sale.objects.create(
            pharmacy=self.pharmacy,
            receipt_number=f'R-{timezone.now().timestamp()}-{quantity}',
            status='COMPLETED',
            payment_status='PAID',
            payment_method=payment_method,
            subtotal=total,
            total=total,
            amount_paid=total,
            sold_by=self.manager,
            completed_at=timezone.now(),
        )
        SaleItem.objects.create(
            sale=sale,
            inventory_item=self.inventory,
            quantity=quantity,
            unit_price=Decimal('200.00'),
            line_total=total,
        )
        return sale

    def test_dashboard_summary_excludes_draft_and_void_sales(self):
        self.client.force_authenticate(self.owner)

        sale = self._create_completed_sale(total=Decimal('1000.00'), payment_method='CASH', quantity=5)
        Sale.objects.create(
            pharmacy=self.pharmacy,
            receipt_number='DRAFT-001',
            status='DRAFT',
            payment_status='PENDING',
            subtotal=Decimal('500.00'),
            total=Decimal('500.00'),
            created_by=self.owner,
        )
        voided = Sale.objects.create(
            pharmacy=self.pharmacy,
            receipt_number='VOID-001',
            status='VOIDED',
            payment_status='PAID',
            subtotal=Decimal('700.00'),
            total=Decimal('700.00'),
            sold_by=self.manager,
            completed_at=timezone.now(),
            voided_at=timezone.now(),
        )

        response = self.client.get('/api/reports/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['sales']['transactions'], 1)
        self.assertEqual(response.data['sales']['revenue'], '1000.00')
        self.assertEqual(response.data['sales']['units_sold'], 5)
        self.assertNotIn('VOID-001', str(response.data))

    def test_payment_method_summary_aggregates_by_method(self):
        self.client.force_authenticate(self.owner)
        self._create_completed_sale(total=Decimal('200.00'), payment_method='CASH', quantity=2)
        self._create_completed_sale(total=Decimal('300.00'), payment_method='POS', quantity=3)
        self._create_completed_sale(total=Decimal('500.00'), payment_method='CASH', quantity=4)

        response = self.client.get('/api/reports/sales/payment-methods/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        grouped = {item['payment_method']: item for item in response.data['results']}
        self.assertEqual(grouped['CASH']['total_amount'], '700.00')
        self.assertEqual(grouped['POS']['total_amount'], '300.00')

    def test_cross_pharmacy_reports_are_isolated(self):
        self.client.force_authenticate(self.owner)
        self._create_completed_sale(total=Decimal('450.00'), payment_method='BANK_TRANSFER', quantity=1)
        other_sale = Sale.objects.create(
            pharmacy=self.other_pharmacy,
            receipt_number='OTHER-001',
            status='COMPLETED',
            payment_status='PAID',
            payment_method='POS',
            subtotal=Decimal('1000.00'),
            total=Decimal('1000.00'),
            amount_paid=Decimal('1000.00'),
            sold_by=self.other_owner,
            completed_at=timezone.now(),
        )
        SaleItem.objects.create(
            sale=other_sale,
            inventory_item=self.other_inventory,
            quantity=2,
            unit_price=Decimal('500.00'),
            line_total=Decimal('1000.00'),
        )

        response = self.client.get('/api/reports/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['sales']['revenue'], '450.00')
        self.assertNotIn('OTHER-001', str(response.data))

    def test_inventory_summary_uses_actual_batch_quantity_and_expiry(self):
        self.client.force_authenticate(self.owner)
        expired_batch = InventoryBatch.objects.create(
            inventory_item=self.inventory,
            batch_number='EXPIRED-001',
            quantity=30,
            expiry_date=timezone.now().date() - timezone.timedelta(days=1),
            cost_per_unit=Decimal('50.00'),
        )
        StockMovement.objects.create(
            movement_type='RECEIVE',
            pharmacy=self.pharmacy,
            inventory_item=self.inventory,
            batch=self.batch,
            quantity_change=+10,
            performed_by=self.owner,
        )
        response = self.client.get('/api/reports/inventory/summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['inventory']['total_units_in_stock'], 40)
        self.assertEqual(response.data['inventory']['expired_batches'], 1)


class OperationalReportsAPITestCase(ReportsAPITestCase):
    def test_operations_summary_aggregates_sales_payments_and_movements(self):
        self.client.force_authenticate(self.owner)
        self._create_completed_sale(total=Decimal('200.00'), payment_method='CASH', quantity=2)
        self._create_completed_sale(total=Decimal('300.00'), payment_method='POS', quantity=3)
        StockMovement.objects.create(
            movement_type='RECEIVE', pharmacy=self.pharmacy,
            inventory_item=self.inventory, batch=self.batch, quantity_change=10,
            performed_by=self.owner,
        )
        StockMovement.objects.create(
            movement_type='DAMAGE', pharmacy=self.pharmacy,
            inventory_item=self.inventory, batch=self.batch, quantity_change=-2,
            performed_by=self.owner,
        )

        response = self.client.get('/api/reports/operations/summary/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['sales']['completed_sales'], 2)
        self.assertEqual(response.data['sales']['gross_sales'], '500.00')
        self.assertEqual(response.data['sales']['cash_received'], '200.00')
        self.assertEqual(response.data['sales']['digital_received'], '300.00')
        self.assertEqual(response.data['sales']['items_sold'], 5)
        self.assertEqual(response.data['inventory_activity']['RECEIVE'], 10)
        self.assertEqual(response.data['inventory_activity']['DAMAGE'], -2)

    def test_low_stock_and_expiry_reports_use_private_inventory_state(self):
        self.client.force_authenticate(self.owner)
        self.inventory.reorder_level = 50
        self.inventory.save(update_fields=['reorder_level', 'updated_at'])
        response = self.client.get('/api/reports/inventory/low-stock/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

        expiry_response = self.client.get('/api/reports/inventory/expiry/?warning_days=30')
        self.assertEqual(expiry_response.status_code, status.HTTP_200_OK)
        self.assertTrue(any(row['batch'] == 'BATCH-001' for row in expiry_response.data['results']))

    def test_top_selling_report_aggregates_completed_sale_items(self):
        self.client.force_authenticate(self.owner)
        self._create_completed_sale(total=Decimal('200.00'), quantity=2)
        self._create_completed_sale(total=Decimal('500.00'), quantity=5)

        response = self.client.get('/api/reports/sales/top-selling/?order_by=quantity')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['results'][0]['quantity_sold'], 7)
        self.assertEqual(response.data['results'][0]['revenue'], '700.00')

    def test_report_date_range_is_validated(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get('/api/reports/operations/summary/?date_from=2026-09-03&date_to=2026-09-02')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_operations_report_isolated_from_other_pharmacy(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get('/api/reports/operations/summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('OTHER-001', str(response.data))
