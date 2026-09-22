"""
Comprehensive tests for Sales/Dispensing functionality.

Test cases cover:
1. Sale creation and lifecycle
2. Sale items and pricing
3. Stock availability and allocation
4. FEFO batch allocation
5. Concurrent sale handling
6. Completion and stock reduction
7. Void/reversal
8. Permissions and cross-pharmacy security
9. Financial calculations
10. Immutable records
"""

from decimal import Decimal
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from pharmacy.models import PharmacyBrand, PharmacyMembership
from medicine.models import Medicine
from inventory.models import PharmacyInventoryItem, InventoryBatch
from sales.models import Sale, SaleItem, SaleItemBatchAllocation, Customer, StockMovement
from sales.serializers import CustomerSerializer
from sales.services import SaleCompletionService, SaleVoidService, FEFOBatchAllocator, generate_receipt_number

User = get_user_model()


class SaleCreationTestCase(TestCase):
    """Test suite for creating sales"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create users
        self.owner = User.objects.create_user(
            email='owner@test.com',
            password='testpass123',
            role='PHARMACY_OWNER'
        )
        self.owner.is_approved = True
        self.owner.is_active = True
        self.owner.save()
        
        # Create pharmacy (VERIFIED)
        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Test Pharmacy',
            brand_name='Test Pharmacy',
            verification_status='VERIFIED'
        )
    
    def test_authorized_user_can_create_sale_draft(self):
        """Test 1: Authorized user can create a sale draft"""
        sale = Sale.objects.create(
            pharmacy=self.pharmacy,
            receipt_number=generate_receipt_number(self.pharmacy.id),
            status='DRAFT',
            created_by=self.owner
        )
        
        self.assertEqual(sale.status, 'DRAFT')
        self.assertEqual(sale.pharmacy, self.pharmacy)
        self.assertEqual(sale.created_by, self.owner)
    
    def test_sale_belongs_to_correct_pharmacy(self):
        """Test 2: Sale belongs to the correct PharmacyBrand"""
        # Create another owner
        owner2 = User.objects.create_user(
            email='owner2@test.com',
            password='testpass123',
            role='PHARMACY_OWNER'
        )
        owner2.is_approved = True
        owner2.save()
        
        pharmacy2 = PharmacyBrand.objects.create(
            owner=owner2,
            legal_name='Pharmacy 2',
            brand_name='Pharmacy 2',
            verification_status='VERIFIED'
        )
        
        # Create sale for pharmacy 2
        sale = Sale.objects.create(
            pharmacy=pharmacy2,
            receipt_number=generate_receipt_number(pharmacy2.id),
            status='DRAFT',
            created_by=owner2
        )
        
        self.assertEqual(sale.pharmacy, pharmacy2)
        self.assertNotEqual(sale.pharmacy, self.pharmacy)
    
    def test_draft_sale_does_not_decrease_stock(self):
        """Test 4: Draft sale does not decrease stock"""
        # Create medicine and inventory
        medicine = Medicine.objects.create(
            generic_name='Paracetamol',
            strength='500mg',
            dosage_form='TABLET'
        )
        
        inventory_item = PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy,
            medicine=medicine,
            selling_price=Decimal('100.00'),
            status='ACTIVE'
        )
        
        batch = InventoryBatch.objects.create(
            inventory_item=inventory_item,
            batch_number='BATCH001',
            quantity=100,
            expiry_date=timezone.now().date() + timezone.timedelta(days=365)
        )
        
        initial_quantity = batch.quantity
        
        # Create draft sale
        sale = Sale.objects.create(
            pharmacy=self.pharmacy,
            receipt_number=generate_receipt_number(self.pharmacy.id),
            status='DRAFT',
            created_by=self.owner
        )
        
        SaleItem.objects.create(
            sale=sale,
            inventory_item=inventory_item,
            quantity=10,
            unit_price=Decimal('100.00'),
            line_total=Decimal('1000.00')
        )
        
        # Batch quantity should not change
        batch.refresh_from_db()
        self.assertEqual(batch.quantity, initial_quantity)


class SaleItemTestCase(TestCase):
    """Test suite for sale items"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.owner = User.objects.create_user(
            email='owner@test.com',
            password='testpass123',
            role='PHARMACY_OWNER'
        )
        self.owner.is_approved = True
        self.owner.save()
        
        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Test Pharmacy',
            brand_name='Test Pharmacy',
            verification_status='VERIFIED'
        )
        
        # Create medicine and inventory
        self.medicine = Medicine.objects.create(
            generic_name='Paracetamol',
            strength='500mg',
            dosage_form='TABLET'
        )
        
        self.inventory = PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy,
            medicine=self.medicine,
            selling_price=Decimal('100.00'),
            status='ACTIVE'
        )
        
        self.sale = Sale.objects.create(
            pharmacy=self.pharmacy,
            receipt_number=generate_receipt_number(self.pharmacy.id),
            status='DRAFT',
            created_by=self.owner
        )
    
    def test_sale_can_contain_multiple_items(self):
        """Test 5: Sale can contain multiple items"""
        item1 = SaleItem.objects.create(
            sale=self.sale,
            inventory_item=self.inventory,
            quantity=5,
            unit_price=Decimal('100.00'),
            line_total=Decimal('500.00')
        )
        
        item2 = SaleItem.objects.create(
            sale=self.sale,
            inventory_item=self.inventory,
            quantity=3,
            unit_price=Decimal('100.00'),
            line_total=Decimal('300.00')
        )
        
        self.assertEqual(self.sale.items.count(), 2)
    
    def test_sale_item_stores_transaction_time_price(self):
        """Test 7: SaleItem stores the transaction-time unit price"""
        # Create item with current price
        item = SaleItem.objects.create(
            sale=self.sale,
            inventory_item=self.inventory,
            quantity=5,
            unit_price=Decimal('100.00'),
            line_total=Decimal('500.00')
        )
        
        # Change inventory price
        self.inventory.selling_price = Decimal('150.00')
        self.inventory.save()
        
        # Item should still have old price
        item.refresh_from_db()
        self.assertEqual(item.unit_price, Decimal('100.00'))


class CustomerLedgerSerializerTestCase(TestCase):
    """Customer ledger fields should be exposed from the real sales totals."""

    def setUp(self):
        self.owner = User.objects.create_user(
            email='owner-ledger@test.com',
            password='testpass123',
            role='PHARMACY_OWNER'
        )
        self.owner.is_approved = True
        self.owner.is_active = True
        self.owner.save()

        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Ledger Pharmacy',
            brand_name='Ledger Pharmacy',
            verification_status='VERIFIED'
        )

        self.customer = Customer.objects.create(
            pharmacy=self.pharmacy,
            first_name='Ada',
            last_name='Adebayo',
            phone_number='08031234567',
            email='ada@example.com',
            customer_type='REGISTERED',
        )

    def test_serializer_exposes_customer_ledger_totals(self):
        sale_one = Sale.objects.create(
            pharmacy=self.pharmacy,
            customer=self.customer,
            receipt_number=generate_receipt_number(self.pharmacy.id),
            status='COMPLETED',
            subtotal=Decimal('600.00'),
            total=Decimal('600.00'),
            amount_paid=Decimal('200.00'),
            payment_status='PARTIAL',
            created_by=self.owner,
            sold_by=self.owner,
        )

        sale_two = Sale.objects.create(
            pharmacy=self.pharmacy,
            customer=self.customer,
            receipt_number=generate_receipt_number(self.pharmacy.id),
            status='COMPLETED',
            subtotal=Decimal('400.00'),
            total=Decimal('400.00'),
            amount_paid=Decimal('400.00'),
            payment_status='PAID',
            created_by=self.owner,
            sold_by=self.owner,
        )

        data = CustomerSerializer(self.customer).data

        self.assertEqual(data['total_sales'], '1000.00')
        self.assertEqual(data['total_paid'], '600.00')
        self.assertEqual(data['outstanding_balance'], '400.00')
        self.assertEqual(data['sales_count'], 2)


class StockAvailabilityTestCase(TestCase):
    """Test suite for stock availability"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.owner = User.objects.create_user(
            email='owner@test.com',
            password='testpass123',
            role='PHARMACY_OWNER'
        )
        self.owner.is_approved = True
        self.owner.save()
        
        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Test Pharmacy',
            brand_name='Test Pharmacy',
            verification_status='VERIFIED'
        )
        
        self.medicine = Medicine.objects.create(
            generic_name='Paracetamol',
            strength='500mg',
            dosage_form='TABLET'
        )
        
        self.inventory = PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy,
            medicine=self.medicine,
            selling_price=Decimal('100.00'),
            status='ACTIVE'
        )
    
    def test_expired_stock_cannot_be_consumed(self):
        """Test 14: Expired batches cannot be consumed"""
        # Create expired batch
        expired_batch = InventoryBatch.objects.create(
            inventory_item=self.inventory,
            batch_number='EXPIRED',
            quantity=100,
            expiry_date=timezone.now().date() - timezone.timedelta(days=1)
        )
        
        # Try to allocate
        with self.assertRaises(ValueError):
            FEFOBatchAllocator.allocate_batches(self.inventory, 10)


class FEFOBatchAllocationTestCase(TestCase):
    """Test suite for FEFO batch allocation"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.owner = User.objects.create_user(
            email='owner@test.com',
            password='testpass123',
            role='PHARMACY_OWNER'
        )
        self.owner.is_approved = True
        self.owner.save()
        
        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Test Pharmacy',
            brand_name='Test Pharmacy',
            verification_status='VERIFIED'
        )
        
        self.medicine = Medicine.objects.create(
            generic_name='Paracetamol',
            strength='500mg',
            dosage_form='TABLET'
        )
        
        self.inventory = PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy,
            medicine=self.medicine,
            selling_price=Decimal('100.00'),
            status='ACTIVE'
        )
    
    def test_earliest_expiry_batch_consumed_first(self):
        """Test 16: Earliest valid expiry batch is consumed first"""
        today = timezone.now().date()
        
        batch_a = InventoryBatch.objects.create(
            inventory_item=self.inventory,
            batch_number='BATCH_A',
            quantity=50,
            expiry_date=today + timezone.timedelta(days=30)
        )
        
        batch_b = InventoryBatch.objects.create(
            inventory_item=self.inventory,
            batch_number='BATCH_B',
            quantity=100,
            expiry_date=today + timezone.timedelta(days=365)
        )
        
        # Allocate 40 units
        allocations = FEFOBatchAllocator.allocate_batches(self.inventory, 40)
        
        # Should use only batch A (earlier expiry)
        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations[0][0].id, batch_a.id)
        self.assertEqual(allocations[0][1], 40)


class SaleCompletionTestCase(TransactionTestCase):
    """Test suite for completing sales"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.owner = User.objects.create_user(
            email='owner@test.com',
            password='testpass123',
            role='PHARMACY_OWNER'
        )
        self.owner.is_approved = True
        self.owner.save()
        
        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Test Pharmacy',
            brand_name='Test Pharmacy',
            verification_status='VERIFIED'
        )
        
        self.medicine = Medicine.objects.create(
            generic_name='Paracetamol',
            strength='500mg',
            dosage_form='TABLET'
        )
        
        self.inventory = PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy,
            medicine=self.medicine,
            selling_price=Decimal('100.00'),
            status='ACTIVE'
        )
        
        self.batch = InventoryBatch.objects.create(
            inventory_item=self.inventory,
            batch_number='BATCH001',
            quantity=100,
            expiry_date=timezone.now().date() + timezone.timedelta(days=365)
        )
    
    def test_completing_sale_decreases_batch_quantity(self):
        """Test 9: Completing a sale decreases batch quantity"""
        sale = Sale.objects.create(
            pharmacy=self.pharmacy,
            receipt_number=generate_receipt_number(self.pharmacy.id),
            status='DRAFT',
            created_by=self.owner
        )
        
        item = SaleItem.objects.create(
            sale=sale,
            inventory_item=self.inventory,
            quantity=20,
            unit_price=Decimal('100.00'),
            line_total=Decimal('2000.00')
        )
        
        initial_quantity = self.batch.quantity
        
        # Complete sale
        SaleCompletionService.complete_sale(sale, self.owner)
        
        # Batch quantity should decrease
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, initial_quantity - 20)
    
    def test_completing_sale_creates_stock_movement(self):
        """Test 10: Completing a sale creates SALE StockMovement"""
        sale = Sale.objects.create(
            pharmacy=self.pharmacy,
            receipt_number=generate_receipt_number(self.pharmacy.id),
            status='DRAFT',
            created_by=self.owner
        )
        
        item = SaleItem.objects.create(
            sale=sale,
            inventory_item=self.inventory,
            quantity=20,
            unit_price=Decimal('100.00'),
            line_total=Decimal('2000.00')
        )
        
        # Complete sale
        SaleCompletionService.complete_sale(sale, self.owner)
        
        # Verify stock movement created
        movements = StockMovement.objects.filter(sale=sale)
        self.assertGreater(movements.count(), 0)
        movement = movements.first()
        self.assertEqual(movement.movement_type, 'SALE')

    def test_voiding_sale_restores_stock_and_creates_reversal_movement(self):
        sale = Sale.objects.create(
            pharmacy=self.pharmacy,
            receipt_number=generate_receipt_number(self.pharmacy.id),
            status='DRAFT',
            created_by=self.owner
        )
        SaleItem.objects.create(
            sale=sale,
            inventory_item=self.inventory,
            quantity=20,
            unit_price=Decimal('100.00'),
            line_total=Decimal('2000.00')
        )

        SaleCompletionService.complete_sale(sale, self.owner)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, 80)

        SaleVoidService.void_sale(sale, self.owner, 'Customer cancelled the purchase')

        self.batch.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.batch.quantity, 100)
        self.assertEqual(sale.status, 'VOIDED')
        self.assertEqual(
            StockMovement.objects.filter(sale=sale, movement_type='VOID').count(),
            1,
        )


class UnverifiedPharmacyTestCase(TestCase):
    """Test suite for unverified pharmacy restrictions"""
    
    def test_unverified_pharmacy_cannot_perform_sales(self):
        """Test 38: Unverified pharmacy cannot perform normal sales"""
        unverified_owner = User.objects.create_user(
            email='unverified@test.com',
            password='testpass123',
            role='PHARMACY_OWNER'
        )
        unverified_owner.is_approved = True
        unverified_owner.save()
        
        unverified_pharmacy = PharmacyBrand.objects.create(
            owner=unverified_owner,
            legal_name='Unverified Pharmacy',
            brand_name='Unverified Pharmacy',
            verification_status='DRAFT'
        )
        
        sale = Sale.objects.create(
            pharmacy=unverified_pharmacy,
            receipt_number=generate_receipt_number(unverified_pharmacy.id),
            status='DRAFT',
            created_by=unverified_owner
        )
        
        # Try to complete should fail
        with self.assertRaises(ValueError):
            SaleCompletionService.validate_sale_completable(sale)


class CustomerCreditAndPaymentTestCase(TestCase):
    """Tests for debt aggregation and customer payment flows on real sale records."""

    def setUp(self):
        self.owner = User.objects.create_user(
            email='credit-owner@test.com',
            password='testpass123',
            role='PHARMACY_OWNER'
        )
        self.owner.is_approved = True
        self.owner.save()

        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Credit Pharmacy',
            brand_name='Credit Pharmacy',
            verification_status='VERIFIED'
        )

        self.customer = Customer.objects.create(
            first_name='Ada',
            last_name='Lovelace',
            phone_number='08012345678',
            email='ada@credit.test',
            pharmacy=self.pharmacy,
            customer_type='REGISTERED',
        )

    def test_customer_credit_balance_uses_completed_sales_only(self):
        Sale.objects.create(
            pharmacy=self.pharmacy,
            customer=self.customer,
            receipt_number=generate_receipt_number(self.pharmacy.id),
            status='COMPLETED',
            subtotal=Decimal('120.00'),
            discount=Decimal('0.00'),
            tax=Decimal('0.00'),
            total=Decimal('120.00'),
            payment_status='PARTIAL',
            amount_paid=Decimal('40.00'),
            sold_by=self.owner,
        )
        Sale.objects.create(
            pharmacy=self.pharmacy,
            customer=self.customer,
            receipt_number=generate_receipt_number(self.pharmacy.id),
            status='COMPLETED',
            subtotal=Decimal('90.00'),
            discount=Decimal('0.00'),
            tax=Decimal('0.00'),
            total=Decimal('90.00'),
            payment_status='PENDING',
            amount_paid=Decimal('0.00'),
            sold_by=self.owner,
        )

        self.assertEqual(self.customer.total_sales, Decimal('210.00'))
        self.assertEqual(self.customer.total_paid, Decimal('40.00'))
        self.assertEqual(self.customer.outstanding_balance, Decimal('170.00'))

    def test_customer_payment_application_updates_sale_and_respects_remaining_balance(self):
        sale = Sale.objects.create(
            pharmacy=self.pharmacy,
            customer=self.customer,
            receipt_number=generate_receipt_number(self.pharmacy.id),
            status='COMPLETED',
            subtotal=Decimal('100.00'),
            discount=Decimal('0.00'),
            tax=Decimal('0.00'),
            total=Decimal('100.00'),
            payment_status='PARTIAL',
            amount_paid=Decimal('25.00'),
            sold_by=self.owner,
        )

        sale.apply_customer_payment(Decimal('20.00'))
        sale.refresh_from_db()

        self.assertEqual(sale.amount_paid, Decimal('45.00'))
        self.assertEqual(sale.payment_status, 'PARTIAL')

        with self.assertRaises(ValueError):
            sale.apply_customer_payment(Decimal('200.00'))

    def test_anonymous_credit_sale_is_rejected(self):
        sale = Sale.objects.create(
            pharmacy=self.pharmacy,
            customer=None,
            receipt_number=generate_receipt_number(self.pharmacy.id),
            status='DRAFT',
            subtotal=Decimal('100.00'),
            discount=Decimal('0.00'),
            tax=Decimal('0.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('0.00'),
            payment_status='PENDING',
            created_by=self.owner,
        )

        with self.assertRaises(ValueError):
            sale.validate_customer_payment_request(Decimal('50.00'))

    def test_customer_payment_later_sets_sale_to_credit_status(self):
        sale = Sale.objects.create(
            pharmacy=self.pharmacy,
            customer=self.customer,
            receipt_number=generate_receipt_number(self.pharmacy.id),
            status='COMPLETED',
            subtotal=Decimal('100.00'),
            discount=Decimal('0.00'),
            tax=Decimal('0.00'),
            total=Decimal('100.00'),
            payment_status='PENDING',
            amount_paid=Decimal('0.00'),
            sold_by=self.owner,
        )

        sale.apply_customer_payment(Decimal('20.00'))
        sale.refresh_from_db()

        self.assertEqual(sale.amount_paid, Decimal('20.00'))
        self.assertEqual(sale.payment_status, 'PARTIAL')
        self.assertEqual(sale.remaining_balance, Decimal('80.00'))
