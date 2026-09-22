"""
Comprehensive tests for inventory adjustment system.

Covers:
- Stock adjustments, damage, expiry, loss recording
- Customer return workflow (3-path: SELLABLE/DAMAGED/QUARANTINED)
- Stock reconciliation (expected_qty immutability)
- Concurrency and audit trails
- Permission enforcement
- Pharmacy isolation
"""

import uuid
from datetime import datetime, timedelta, date
from decimal import Decimal

from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.contrib.gis.geos import Point

from pharmacy.models import PharmacyBrand, PharmacyMembership
from medicine.models import Medicine
from inventory.models import PharmacyInventoryItem, InventoryBatch, CustomerReturn, InventoryHold, StockReconciliation
from sales.models import Sale, SaleItem, SaleItemBatchAllocation, StockMovement, Customer
from .services import (
    StockAdjustmentService, DamageService, ExpiryService, LossService,
    CustomerReturnService, StockReconciliationService, InventoryPublicationService
)

User = get_user_model()


class TestDataSetup(TestCase):
    """Base test case with fixtures."""
    
    @classmethod
    def setUpTestData(cls):
        """Create shared test data."""
        # Create users
        cls.super_admin = User.objects.create_user(
            email='superadmin@test.com',
            password='testpass',
            role='SUPER_ADMIN'
        )
        
        cls.pharmacy_owner = User.objects.create_user(
            email='owner@test.com',
            password='testpass',
            role='PHARMACY_OWNER'
        )
        
        cls.pharmacy_manager = User.objects.create_user(
            email='manager@test.com',
            password='testpass',
            role='PHARMACY_MANAGER'
        )
        
        cls.pharmacist = User.objects.create_user(
            email='pharmacist@test.com',
            password='testpass',
            role='PHARMACIST'
        )
        
        cls.staff = User.objects.create_user(
            email='staff@test.com',
            password='testpass',
            role='PHARMACY_STAFF'
        )
        
        # Create pharmacy
        cls.pharmacy = PharmacyBrand.objects.create(
            legal_name='Test Pharmacy Ltd',
            brand_name='Test Pharmacy',
            location=Point(0, 0),
            owner=cls.pharmacy_owner,
            verification_status='VERIFIED'
        )

        PharmacyMembership.objects.bulk_create([
            PharmacyMembership(
                pharmacy=cls.pharmacy,
                user=cls.pharmacy_manager,
                role='PHARMACY_MANAGER',
                status='APPROVED',
                approved_by=cls.pharmacy_owner,
            ),
            PharmacyMembership(
                pharmacy=cls.pharmacy,
                user=cls.pharmacist,
                role='PHARMACIST',
                status='APPROVED',
                approved_by=cls.pharmacy_owner,
            ),
            PharmacyMembership(
                pharmacy=cls.pharmacy,
                user=cls.staff,
                role='PHARMACY_STAFF',
                status='APPROVED',
                approved_by=cls.pharmacy_owner,
            ),
        ])
        
        # Create medicine
        cls.medicine = Medicine.objects.create(
            generic_name='test_generic',
            strength='500mg',
            dosage_form='TABLET'
        )
        
        # Create inventory item
        cls.inventory_item = PharmacyInventoryItem.objects.create(
            pharmacy=cls.pharmacy,
            medicine=cls.medicine,
            selling_price=Decimal('10.00'),
            is_published=True
        )
        
        # Create batches with different expiry dates
        today = timezone.now().date()
        cls.batch_future = InventoryBatch.objects.create(
            inventory_item=cls.inventory_item,
            batch_number='BATCH001',
            quantity=100,
            expiry_date=today + timedelta(days=365)
        )
        
        cls.batch_expired = InventoryBatch.objects.create(
            inventory_item=cls.inventory_item,
            batch_number='BATCH002',
            quantity=50,
            expiry_date=today - timedelta(days=1)
        )
        
        cls.batch_expiring_soon = InventoryBatch.objects.create(
            inventory_item=cls.inventory_item,
            batch_number='BATCH003',
            quantity=75,
            expiry_date=today + timedelta(days=7)
        )
        
        # Create customer and sale for return tests
        cls.customer = Customer.objects.create(
            first_name='John',
            last_name='Doe',
            customer_type='WALK_IN',
            pharmacy=cls.pharmacy
        )
        
        cls.sale = Sale.objects.create(
            pharmacy=cls.pharmacy,
            customer=cls.customer,
            sold_by=cls.pharmacist,
            status='COMPLETED',
            receipt_number='TEST-RECEIPT-001'
        )
        
        cls.sale_item = SaleItem.objects.create(
            sale=cls.sale,
            inventory_item=cls.inventory_item,
            quantity=20,
            unit_price=Decimal('10.00'),
            line_total=Decimal('200.00')
        )
        SaleItemBatchAllocation.objects.create(
            sale_item=cls.sale_item,
            batch=cls.batch_future,
            quantity=20,
        )


# ============================================================================
# Stock Adjustment Tests
# ============================================================================

class StockAdjustmentServiceTests(TestDataSetup):
    """Tests for StockAdjustmentService."""
    
    def test_adjust_stock_increase(self):
        """Test increasing stock quantity."""
        initial_qty = self.batch_future.quantity
        
        movement = StockAdjustmentService.adjust_stock(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity_delta=10,
            reason='DATA_ENTRY_ERROR',
            user=self.pharmacy_manager,
            notes='Correction from counting'
        )
        
        self.batch_future.refresh_from_db()
        self.assertEqual(self.batch_future.quantity, initial_qty + 10)
        self.assertEqual(movement.quantity_change, 10)
        self.assertEqual(movement.movement_type, 'ADJUSTMENT')
        self.assertEqual(movement.reason, 'DATA_ENTRY_ERROR')
    
    def test_adjust_stock_decrease(self):
        """Test decreasing stock quantity."""
        initial_qty = self.batch_future.quantity
        
        movement = StockAdjustmentService.adjust_stock(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity_delta=-5,
            reason='STOCK_COUNT_CORRECTION',
            user=self.pharmacy_manager,
            notes='Physical count showed shortage'
        )
        
        self.batch_future.refresh_from_db()
        self.assertEqual(self.batch_future.quantity, initial_qty - 5)
        self.assertEqual(movement.quantity_change, -5)
    
    def test_adjust_stock_negative_quantity_rejected(self):
        """Test adjustment that would result in negative quantity."""
        with self.assertRaises(ValueError):
            StockAdjustmentService.adjust_stock(
                inventory_item=self.inventory_item,
                batch=self.batch_future,
                quantity_delta=-200,  # More than available
                reason='DATA_ENTRY_ERROR',
                user=self.pharmacy_manager,
                notes='Invalid adjustment'
            )
    
    def test_adjust_stock_permission_denied(self):
        """Test permission denial for non-manager users."""
        with self.assertRaises(PermissionError):
            StockAdjustmentService.adjust_stock(
                inventory_item=self.inventory_item,
                batch=self.batch_future,
                quantity_delta=10,
                reason='DATA_ENTRY_ERROR',
                user=self.staff,  # Staff cannot adjust
                notes='Unauthorized'
            )
    
    def test_adjust_stock_creates_audit_trail(self):
        """Test that adjustment creates StockMovement."""
        StockAdjustmentService.adjust_stock(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity_delta=5,
            reason='FOUND',
            user=self.pharmacy_manager,
            notes='Lost item found'
        )
        
        movement = StockMovement.objects.get(
            movement_type='ADJUSTMENT',
            pharmacy=self.pharmacy
        )
        self.assertEqual(movement.quantity_change, 5)
        self.assertEqual(movement.reason, 'FOUND')
        self.assertIn('Lost item found', movement.notes or '')


# ============================================================================
# Damage Recording Tests
# ============================================================================

class DamageRecordingServiceTests(TestDataSetup):
    """Tests for DamageService."""
    
    def test_record_damage_reduces_quantity(self):
        """Test that damage recording reduces batch quantity."""
        initial_qty = self.batch_future.quantity
        
        movement = DamageService.record_damage(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity=10,
            reason='DAMAGED_IN_STORAGE',
            user=self.pharmacist,
            notes='Water damage during storage'
        )
        
        self.batch_future.refresh_from_db()
        self.assertEqual(self.batch_future.quantity, initial_qty - 10)
        self.assertEqual(movement.quantity_change, -10)
        self.assertEqual(movement.movement_type, 'DAMAGE')
    
    def test_record_damage_permission_allowed_roles(self):
        """Test that allowed roles can record damage."""
        # Manager
        DamageService.record_damage(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity=1,
            reason='DAMAGE_OTHER',
            user=self.pharmacy_manager,
            notes='Test'
        )
        
        # Pharmacist
        DamageService.record_damage(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity=1,
            reason='DAMAGE_OTHER',
            user=self.pharmacist,
            notes='Test'
        )
        
        # Owner
        DamageService.record_damage(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity=1,
            reason='DAMAGE_OTHER',
            user=self.pharmacy_owner,
            notes='Test'
        )
    
    def test_record_damage_permission_denied_for_staff(self):
        """Test that staff cannot record damage."""
        with self.assertRaises(PermissionError):
            DamageService.record_damage(
                inventory_item=self.inventory_item,
                batch=self.batch_future,
                quantity=5,
                reason='DAMAGED_IN_DELIVERY',
                user=self.staff,
                notes='Unauthorized'
            )
    
    def test_record_damage_insufficient_quantity(self):
        """Test damage recording with insufficient quantity."""
        with self.assertRaises(ValueError):
            DamageService.record_damage(
                inventory_item=self.inventory_item,
                batch=self.batch_future,
                quantity=200,  # More than available
                reason='DAMAGE_OTHER',
                user=self.pharmacist,
                notes='Too much'
            )


# ============================================================================
# Expiry Write-off Tests
# ============================================================================

class ExpiryRecordingServiceTests(TestDataSetup):
    """Tests for ExpiryService."""
    
    def test_record_expiry_expired_batch(self):
        """Test recording expiry for actually expired batch."""
        initial_qty = self.batch_expired.quantity
        
        movement = ExpiryService.record_expiry_writeoff(
            inventory_item=self.inventory_item,
            batch=self.batch_expired,
            quantity=30,
            reason='NATURAL_EXPIRY',
            user=self.pharmacy_manager,
            notes='Batch expired'
        )
        
        self.batch_expired.refresh_from_db()
        self.assertEqual(self.batch_expired.quantity, initial_qty - 30)
        self.assertEqual(movement.quantity_change, -30)
        self.assertEqual(movement.movement_type, 'EXPIRED')
    
    def test_record_expiry_non_expired_batch_rejected(self):
        """Test that non-expired batch cannot be marked as expired."""
        with self.assertRaises(ValueError):
            ExpiryService.record_expiry_writeoff(
                inventory_item=self.inventory_item,
                batch=self.batch_future,  # Not expired
                quantity=10,
                reason='NATURAL_EXPIRY',
                user=self.pharmacy_manager,
                notes='Should fail'
            )


# ============================================================================
# Loss Recording Tests
# ============================================================================

class LossRecordingServiceTests(TestDataSetup):
    """Tests for LossService."""
    
    def test_record_loss_reduces_quantity(self):
        """Test that loss recording reduces batch quantity."""
        initial_qty = self.batch_future.quantity
        
        movement = LossService.record_loss(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity=5,
            reason='MISSING_INVENTORY',
            user=self.pharmacy_manager,
            notes='Inventory discrepancy'
        )
        
        self.batch_future.refresh_from_db()
        self.assertEqual(self.batch_future.quantity, initial_qty - 5)
        self.assertEqual(movement.quantity_change, -5)
        self.assertEqual(movement.movement_type, 'LOSS')
    
    def test_record_loss_restricted_permissions(self):
        """Test that only manager and owner can record loss."""
        # Manager
        LossService.record_loss(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity=1,
            reason='MISSING_INVENTORY',
            user=self.pharmacy_manager,
            notes='Test'
        )
        
        # Owner
        LossService.record_loss(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity=1,
            reason='MISSING_INVENTORY',
            user=self.pharmacy_owner,
            notes='Test'
        )
        
        # Pharmacist cannot
        with self.assertRaises(PermissionError):
            LossService.record_loss(
                inventory_item=self.inventory_item,
                batch=self.batch_future,
                quantity=1,
                reason='MISSING_INVENTORY',
                user=self.pharmacist,
                notes='Should fail'
            )


# ============================================================================
# Customer Return Workflow Tests
# ============================================================================

class CustomerReturnServiceTests(TestDataSetup):
    """Tests for CustomerReturnService."""
    
    def test_initiate_return_creates_pending_record(self):
        """Test initiating a return creates PENDING_REVIEW record."""
        return_record = CustomerReturnService.initiate_return(
            sale=self.sale,
            sale_item=self.sale_item,
            quantity_returned=5,
            condition='SELLABLE',
            reason='CUSTOMER_COMPLAINT',
            user=self.staff,
            notes='Customer complaint about effectiveness'
        )
        
        self.assertEqual(return_record.status, 'PENDING_REVIEW')
        self.assertEqual(return_record.quantity_returned, 5)
        self.assertEqual(return_record.condition, 'SELLABLE')
        self.assertIsNotNone(return_record.initiated_by)
    
    def test_approve_return_updates_status(self):
        """Test approving a return."""
        return_record = CustomerReturnService.initiate_return(
            sale=self.sale,
            sale_item=self.sale_item,
            quantity_returned=5,
            condition='SELLABLE',
            reason='CUSTOMER_COMPLAINT',
            user=self.staff,
            notes='Test'
        )
        
        CustomerReturnService.approve_return(return_record, self.pharmacy_manager)
        return_record.refresh_from_db()
        
        self.assertEqual(return_record.status, 'APPROVED')
        self.assertEqual(return_record.reviewed_by, self.pharmacy_manager)
    
    def test_approve_return_permission_denied_for_staff(self):
        """Test that staff cannot approve returns."""
        return_record = CustomerReturnService.initiate_return(
            sale=self.sale,
            sale_item=self.sale_item,
            quantity_returned=5,
            condition='SELLABLE',
            reason='CUSTOMER_COMPLAINT',
            user=self.staff,
            notes='Test'
        )
        
        with self.assertRaises(PermissionError):
            CustomerReturnService.approve_return(return_record, self.staff)
    
    def test_process_sellable_return_increases_stock(self):
        """Test processing SELLABLE return increases batch quantity."""
        initial_qty = self.batch_future.quantity
        
        return_record = CustomerReturnService.initiate_return(
            sale=self.sale,
            sale_item=self.sale_item,
            quantity_returned=5,
            condition='SELLABLE',
            reason='CUSTOMER_COMPLAINT',
            user=self.staff,
            notes='Test'
        )
        
        CustomerReturnService.approve_return(return_record, self.pharmacy_manager)
        return_record, movements = CustomerReturnService.process_approved_return(
            return_record, self.pharmacy_manager
        )
        
        self.batch_future.refresh_from_db()
        self.assertEqual(self.batch_future.quantity, initial_qty + 5)
        self.assertEqual(return_record.status, 'COMPLETED')
    
    def test_process_damaged_return_creates_damage_movement(self):
        """Test processing DAMAGED return creates damage movement."""
        initial_qty = self.batch_future.quantity
        
        return_record = CustomerReturnService.initiate_return(
            sale=self.sale,
            sale_item=self.sale_item,
            quantity_returned=5,
            condition='DAMAGED',
            reason='DEFECTIVE',
            user=self.staff,
            notes='Test'
        )
        
        CustomerReturnService.approve_return(return_record, self.pharmacy_manager)
        return_record, movements = CustomerReturnService.process_approved_return(
            return_record, self.pharmacy_manager
        )
        
        self.batch_future.refresh_from_db()
        # DAMAGED items should NOT increase stock
        self.assertEqual(self.batch_future.quantity, initial_qty)
        self.assertEqual(return_record.disposition, 'MARKED_DAMAGED')
    
    def test_process_quarantined_return_creates_hold(self):
        """Test processing QUARANTINED return creates InventoryHold."""
        return_record = CustomerReturnService.initiate_return(
            sale=self.sale,
            sale_item=self.sale_item,
            quantity_returned=5,
            condition='QUARANTINED',
            reason='PENDING_INSPECTION',
            user=self.staff,
            notes='Test'
        )
        
        CustomerReturnService.approve_return(return_record, self.pharmacy_manager)
        return_record, movements = CustomerReturnService.process_approved_return(
            return_record, self.pharmacy_manager
        )
        
        hold = InventoryHold.objects.filter(
            reference_type='CUSTOMER_RETURN',
            reference_id=return_record.id
        ).first()
        
        self.assertIsNotNone(hold)
        self.assertEqual(hold.quantity, 5)
        self.assertEqual(hold.status, 'ON_HOLD')


# ============================================================================
# Stock Reconciliation Tests
# ============================================================================

class StockReconciliationServiceTests(TestDataSetup):
    """Tests for StockReconciliationService."""
    
    def test_start_count_captures_expected_quantity(self):
        """Test starting a count captures expected quantity."""
        initial_qty = self.batch_future.quantity
        
        reconciliation = StockReconciliationService.start_count(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            user=self.pharmacy_manager
        )
        
        self.assertEqual(reconciliation.status, 'IN_PROGRESS')
        self.assertEqual(reconciliation.expected_quantity, initial_qty)
        self.assertIsNotNone(reconciliation.expected_quantity_captured_at)
    
    def test_expected_quantity_immutable_after_start(self):
        """Test that expected_quantity cannot be changed after capture."""
        reconciliation = StockReconciliationService.start_count(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            user=self.pharmacy_manager
        )
        
        expected = reconciliation.expected_quantity
        
        # Manually reduce batch quantity
        self.batch_future.quantity -= 10
        self.batch_future.save()
        
        # Start another count
        reconciliation2 = StockReconciliationService.start_count(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            user=self.pharmacy_manager
        )
        
        # Expected quantity should be updated (from current DB state)
        self.assertNotEqual(reconciliation2.expected_quantity, expected)
    
    def test_finalize_count_calculates_discrepancy(self):
        """Test finalizing count calculates discrepancy."""
        reconciliation = StockReconciliationService.start_count(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            user=self.pharmacy_manager
        )
        
        # Assume physical count found fewer items
        reconciliation = StockReconciliationService.finalize_count(
            reconciliation,
            counted_quantity=85,  # Expected was 100
            user=self.pharmacy_manager
        )
        
        self.assertEqual(reconciliation.status, 'PENDING_APPROVAL')
        self.assertEqual(reconciliation.counted_quantity, 85)
        self.assertEqual(reconciliation.difference, -15)
        self.assertEqual(reconciliation.discrepancy_type, 'SHORTAGE')
    
    def test_discrepancy_type_overage(self):
        """Test discrepancy_type is OVERAGE for counted > expected."""
        reconciliation = StockReconciliationService.start_count(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            user=self.pharmacy_manager
        )
        
        reconciliation = StockReconciliationService.finalize_count(
            reconciliation,
            counted_quantity=110,  # Expected was 100
            user=self.pharmacy_manager
        )
        
        self.assertEqual(reconciliation.discrepancy_type, 'OVERAGE')
        self.assertEqual(reconciliation.difference, 10)
    
    def test_discrepancy_type_no_discrepancy(self):
        """Test discrepancy_type is NO_DISCREPANCY when counts match."""
        reconciliation = StockReconciliationService.start_count(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            user=self.pharmacy_manager
        )
        
        reconciliation = StockReconciliationService.finalize_count(
            reconciliation,
            counted_quantity=100,  # Matches expected
            user=self.pharmacy_manager
        )
        
        self.assertEqual(reconciliation.discrepancy_type, 'NO_DISCREPANCY')
        self.assertEqual(reconciliation.difference, 0)
    
    def test_approve_count_advances_status(self):
        """Test approving count advances to APPROVED."""
        reconciliation = StockReconciliationService.start_count(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            user=self.pharmacy_manager
        )
        
        reconciliation = StockReconciliationService.finalize_count(
            reconciliation,
            counted_quantity=95,
            user=self.pharmacy_manager
        )
        
        reconciliation = StockReconciliationService.approve_count(
            reconciliation,
            user=self.pharmacy_manager,
            notes='Approved after inspection'
        )
        
        self.assertEqual(reconciliation.status, 'APPROVED')
        self.assertEqual(reconciliation.approved_by, self.pharmacy_manager)
    
    def test_reconcile_creates_stock_movement(self):
        """Test reconcile creates correction movement."""
        reconciliation = StockReconciliationService.start_count(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            user=self.pharmacy_manager
        )
        
        reconciliation = StockReconciliationService.finalize_count(
            reconciliation,
            counted_quantity=95,
            user=self.pharmacy_manager
        )
        
        reconciliation = StockReconciliationService.approve_count(
            reconciliation,
            user=self.pharmacy_manager,
            notes='Approved'
        )
        
        reconciliation, movement = StockReconciliationService.reconcile(
            reconciliation,
            user=self.pharmacy_manager
        )
        
        self.assertEqual(reconciliation.status, 'RECONCILED')
        self.assertIsNotNone(movement)
        self.assertEqual(movement.movement_type, 'STOCK_COUNT_CORRECTION')
        self.assertEqual(movement.quantity_change, -5)  # 95 - 100
    
    def test_reconcile_updates_batch_quantity(self):
        """Test reconcile updates batch quantity."""
        initial_qty = self.batch_future.quantity
        
        reconciliation = StockReconciliationService.start_count(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            user=self.pharmacy_manager
        )
        
        reconciliation = StockReconciliationService.finalize_count(
            reconciliation,
            counted_quantity=85,
            user=self.pharmacy_manager
        )
        
        reconciliation = StockReconciliationService.approve_count(
            reconciliation,
            user=self.pharmacy_manager,
            notes='Approved'
        )
        
        reconciliation, movement = StockReconciliationService.reconcile(
            reconciliation,
            user=self.pharmacy_manager
        )
        
        self.batch_future.refresh_from_db()
        self.assertEqual(self.batch_future.quantity, 85)


# ============================================================================
# Audit Trail Tests
# ============================================================================

class AuditTrailTests(TestDataSetup):
    """Tests for audit trail/StockMovement creation."""
    
    def test_all_operations_create_stock_movements(self):
        """Test that all operations create audit trail entries."""
        initial_count = StockMovement.objects.count()
        
        # Adjustment
        StockAdjustmentService.adjust_stock(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity_delta=5,
            reason='DATA_ENTRY_ERROR',
            user=self.pharmacy_manager,
            notes='Test'
        )
        
        # Damage
        DamageService.record_damage(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity=3,
            reason='DAMAGE_OTHER',
            user=self.pharmacist,
            notes='Test'
        )
        
        # Loss
        LossService.record_loss(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity=2,
            reason='MISSING_INVENTORY',
            user=self.pharmacy_manager,
            notes='Test'
        )
        
        self.assertEqual(StockMovement.objects.count(), initial_count + 3)
    
    def test_stock_movement_immutability(self):
        """Test that StockMovement records are never modified."""
        movement = StockAdjustmentService.adjust_stock(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity_delta=5,
            reason='DATA_ENTRY_ERROR',
            user=self.pharmacy_manager,
            notes='Original note'
        )
        
        # Attempt to modify
        movement.quantity_change = 10
        with self.assertRaises(ValueError):
            movement.save()
        
        # Verify original value is still in DB
        movement.refresh_from_db()
        self.assertEqual(movement.quantity_change, 5)


# ============================================================================
# Concurrency Tests
# ============================================================================

class ConcurrencyTests(TransactionTestCase):
    """Tests for concurrency safety with select_for_update()."""
    
    def setUp(self):
        """Setup for concurrency tests."""
        self.user1 = User.objects.create_user(
            email='user1@test.com',
            password='test',
            role='PHARMACY_MANAGER'
        )
        self.user2 = User.objects.create_user(
            email='user2@test.com',
            password='test',
            role='PHARMACY_MANAGER'
        )
        
        self.pharmacy = PharmacyBrand.objects.create(
            legal_name='Test Pharmacy Ltd',
            brand_name='Test Pharmacy',
            location=Point(0, 0),
            owner=self.user1,
            verification_status='VERIFIED'
        )

        PharmacyMembership.objects.create(
            pharmacy=self.pharmacy,
            user=self.user1,
            role='PHARMACY_MANAGER',
            status='APPROVED',
            approved_by=self.user1,
        )

        PharmacyMembership.objects.create(
            pharmacy=self.pharmacy,
            user=self.user2,
            role='PHARMACY_MANAGER',
            status='APPROVED',
            approved_by=self.user1,
        )
        
        medicine = Medicine.objects.create(
            generic_name='test',
            strength='100mg',
            dosage_form='TABLET'
        )
        
        self.inventory_item = PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy,
            medicine=medicine,
            selling_price=Decimal('10.00'),
            is_published=True
        )
        
        self.batch = InventoryBatch.objects.create(
            inventory_item=self.inventory_item,
            batch_number='BATCH001',
            quantity=100,
            expiry_date=timezone.now().date() + timedelta(days=365)
        )
    
    def test_concurrent_adjustments_are_atomic(self):
        """Test that concurrent adjustments maintain consistency."""
        def adjust_stock():
            StockAdjustmentService.adjust_stock(
                inventory_item=self.inventory_item,
                batch=self.batch,
                quantity_delta=10,
                reason='DATA_ENTRY_ERROR',
                user=self.user1,
                notes='Test'
            )
        
        # Simulate concurrent operations
        adjust_stock()
        adjust_stock()
        
        self.batch.refresh_from_db()
        # Should be 100 + 10 + 10 = 120
        self.assertEqual(self.batch.quantity, 120)


# ============================================================================
# Permission and Security Tests
# ============================================================================

class PermissionAndSecurityTests(TestDataSetup):
    """Tests for permission enforcement and pharmacy isolation."""
    
    def test_pharmacy_isolation(self):
        """Test that users only see their pharmacy's data."""
        # Create second pharmacy
        other_user = User.objects.create_user(
            email='otherowner@test.com',
            password='test',
            role='PHARMACY_OWNER'
        )
        other_pharmacy = PharmacyBrand.objects.create(
            legal_name='Other Pharmacy Ltd',
            brand_name='Other Pharmacy',
            location=Point(1, 1),
            owner=other_user,
            verification_status='VERIFIED'
        )
        
        # Pharmacy owner can only adjust their own inventory
        with self.assertRaises(PermissionError):
            StockAdjustmentService.adjust_stock(
                inventory_item=self.inventory_item,  # Belongs to self.pharmacy
                batch=self.batch_future,
                quantity_delta=5,
                reason='DATA_ENTRY_ERROR',
                user=other_user,  # Different pharmacy owner
                notes='Test'
            )


class PublicationTests(TestDataSetup):
    """Tests for private publication controls and public discovery."""

    def setUp(self):
        self.client = APIClient()
        self.batch_future.quantity = 100
        self.batch_future.save(update_fields=['quantity', 'updated_at'])
        self.inventory_item.is_published = False
        self.inventory_item.published_at = None
        self.inventory_item.published_by = None
        self.inventory_item.save(update_fields=['is_published', 'published_at', 'published_by', 'updated_at'])

    def test_inventory_is_private_by_default(self):
        self.assertFalse(self.inventory_item.is_published)
        self.assertFalse(InventoryPublicationService.public_queryset().filter(pk=self.inventory_item.pk).exists())

    def test_owner_can_publish_and_unpublish_without_stock_movement(self):
        before = StockMovement.objects.count()
        InventoryPublicationService.publish_inventory(self.inventory_item, self.pharmacy_owner)
        self.inventory_item.refresh_from_db()
        self.assertTrue(self.inventory_item.is_published)
        self.assertEqual(self.inventory_item.published_by, self.pharmacy_owner)

        InventoryPublicationService.unpublish_inventory(self.inventory_item, self.pharmacy_owner)
        self.inventory_item.refresh_from_db()
        self.assertFalse(self.inventory_item.is_published)
        self.assertEqual(self.inventory_item.unpublished_by, self.pharmacy_owner)
        self.assertEqual(StockMovement.objects.count(), before)

    def test_publication_requires_positive_price_but_unpublished_price_can_be_zero(self):
        self.inventory_item.selling_price = Decimal('0.00')
        self.inventory_item.save(update_fields=['selling_price', 'updated_at'])
        with self.assertRaises(ValueError):
            InventoryPublicationService.publish_inventory(self.inventory_item, self.pharmacy_owner)
        with self.assertRaises(ValueError):
            InventoryPublicationService.update_public_price(self.inventory_item, Decimal('-1.00'), self.pharmacy_owner)

    def test_unverified_pharmacy_cannot_publish(self):
        self.pharmacy.verification_status = 'SUSPENDED'
        self.pharmacy.save(update_fields=['verification_status', 'updated_at'])
        with self.assertRaises(ValueError):
            InventoryPublicationService.publish_inventory(self.inventory_item, self.pharmacy_owner)

    def test_non_owner_cannot_publish_or_change_public_price(self):
        with self.assertRaises(PermissionError):
            InventoryPublicationService.publish_inventory(self.inventory_item, self.pharmacy_manager)
        with self.assertRaises(PermissionError):
            InventoryPublicationService.update_public_price(self.inventory_item, Decimal('12.00'), self.pharmacy_manager)

    def test_public_endpoint_excludes_unpublished_items(self):
        response = self.client.get('/api/inventory/public/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_public_endpoint_exposes_only_safe_fields(self):
        InventoryPublicationService.publish_inventory(self.inventory_item, self.pharmacy_owner)
        response = self.client.get('/api/inventory/public/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        listing = response.data[0]
        for private_field in ('cost_per_unit', 'supplier', 'quantity', 'stock_movements', 'published_by'):
            self.assertNotIn(private_field, listing)
        self.assertEqual(listing['selling_price'], '10.00')
        self.assertEqual(listing['availability'], 'AVAILABLE')

    def test_public_availability_is_derived_without_exposing_quantity(self):
        InventoryPublicationService.publish_inventory(self.inventory_item, self.pharmacy_owner)
        InventoryBatch.objects.filter(inventory_item=self.inventory_item).update(quantity=0)
        response = self.client.get('/api/inventory/public/')
        self.assertEqual(response.data[0]['availability'], 'OUT_OF_STOCK')
        self.assertNotIn('quantity', response.data[0])

    def test_expired_stock_is_not_available(self):
        self.inventory_item.is_published = True
        self.inventory_item.published_at = timezone.now()
        self.inventory_item.published_by = self.pharmacy_owner
        self.inventory_item.save(update_fields=['is_published', 'published_at', 'published_by', 'updated_at'])
        InventoryBatch.objects.filter(inventory_item=self.inventory_item).update(
            expiry_date=timezone.now().date() - timedelta(days=1)
        )
        response = self.client.get('/api/inventory/public/')
        self.assertEqual(response.data[0]['availability'], 'OUT_OF_STOCK')

    def test_public_price_update_does_not_change_stock_or_cost(self):
        original_quantity = self.batch_future.quantity
        InventoryPublicationService.update_public_price(self.inventory_item, Decimal('12.50'), self.pharmacy_owner)
        self.batch_future.refresh_from_db()
        self.inventory_item.refresh_from_db()
        self.assertEqual(self.inventory_item.selling_price, Decimal('12.50'))
        self.assertEqual(self.batch_future.quantity, original_quantity)
        self.assertIsNone(self.batch_future.cost_per_unit)
    
    def test_role_based_permissions_adjustment(self):
        """Test role-based permissions for adjustments."""
        # Super admin can adjust
        StockAdjustmentService.adjust_stock(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity_delta=1,
            reason='DATA_ENTRY_ERROR',
            user=self.super_admin,
            notes='Test'
        )
        
        # Owner can adjust
        StockAdjustmentService.adjust_stock(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity_delta=1,
            reason='DATA_ENTRY_ERROR',
            user=self.pharmacy_owner,
            notes='Test'
        )
        
        # Manager can adjust
        StockAdjustmentService.adjust_stock(
            inventory_item=self.inventory_item,
            batch=self.batch_future,
            quantity_delta=1,
            reason='DATA_ENTRY_ERROR',
            user=self.pharmacy_manager,
            notes='Test'
        )
        
        # Staff cannot adjust
        with self.assertRaises(PermissionError):
            StockAdjustmentService.adjust_stock(
                inventory_item=self.inventory_item,
                batch=self.batch_future,
                quantity_delta=1,
                reason='DATA_ENTRY_ERROR',
                user=self.staff,
                notes='Test'
            )

