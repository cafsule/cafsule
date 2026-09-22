"""
Comprehensive tests for Medicine Catalog and Pharmacy Inventory.

Tests cover:
1. Medicine catalog creation and access
2. Pharmacy inventory management
3. Batch management with expiry tracking
4. Publication workflow and verification requirements
5. Permission enforcement and cross-pharmacy isolation
6. Price and status validation
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from datetime import date, timedelta
from decimal import Decimal

from medicine.models import Medicine
from inventory.models import PharmacyInventoryItem, InventoryBatch
from pharmacy.models import PharmacyBrand, PharmacyMembership

User = get_user_model()


class MedicineCreationTests(TestCase):
    """Test medicine catalog creation and management"""
    
    def setUp(self):
        self.client = APIClient()
        
        # Create admin user
        self.admin = User.objects.create_user(
            email='admin@platform.com',
            password='testpass123!',
            first_name='Admin',
            last_name='User',
            role='PLATFORM_ADMIN'
        )
        self.admin.is_verified = True
        self.admin.is_active = True
        self.admin.save()
        
        # Create pharmacy staff user
        self.staff = User.objects.create_user(
            email='staff@pharmacy.com',
            password='testpass123!',
            first_name='Pharmacy',
            last_name='Staff',
            role='PHARMACIST'
        )
        self.staff.is_verified = True
        self.staff.is_active = True
        self.staff.save()
    
    def test_admin_can_create_medicine(self):
        """Test that PLATFORM_ADMIN can create medicines"""
        self.client.force_authenticate(user=self.admin)
        
        payload = {
            'generic_name': 'Paracetamol',
            'brand_name': 'Panadol',
            'strength': '500mg',
            'dosage_form': 'TABLET',
            'route': 'ORAL',
            'manufacturer': 'Pharma Corp',
            'pack_size': 10,
            'pack_size_unit': 'UNIT'
        }
        
        response = self.client.post('/api/medicine/medicines/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        medicine = Medicine.objects.get(generic_name='Paracetamol')
        self.assertEqual(medicine.brand_name, 'Panadol')
        self.assertEqual(medicine.created_by_id, self.admin.id)
    
    def test_staff_cannot_create_medicine(self):
        """Test that pharmacy staff cannot create medicines"""
        self.client.force_authenticate(user=self.staff)
        
        payload = {
            'generic_name': 'Amoxicillin',
            'strength': '500mg',
            'dosage_form': 'CAPSULE',
            'route': 'ORAL'
        }
        
        response = self.client.post('/api/medicine/medicines/', payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_staff_can_view_medicines(self):
        """Test that pharmacy staff can view medicines"""
        # Create medicine
        medicine = Medicine.objects.create(
            generic_name='Ibuprofen',
            strength='200mg',
            dosage_form='TABLET',
            route='ORAL',
            created_by=self.admin
        )
        
        self.client.force_authenticate(user=self.staff)
        response = self.client.get('/api/medicine/medicines/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['generic_name'], 'Ibuprofen')
    
    def test_medicine_search(self):
        """Test medicine search functionality"""
        # Create medicines
        Medicine.objects.create(
            generic_name='Paracetamol',
            brand_name='Panadol',
            strength='500mg',
            dosage_form='TABLET',
            created_by=self.admin
        )
        
        Medicine.objects.create(
            generic_name='Aspirin',
            brand_name='Bayer',
            strength='100mg',
            dosage_form='TABLET',
            created_by=self.admin
        )
        
        self.client.force_authenticate(user=self.staff)
        
        response = self.client.get('/api/medicine/medicines/search/?q=paracetamol')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['generic_name'], 'Paracetamol')


class PharmacyInventoryTests(TestCase):
    """Test pharmacy inventory creation and management"""
    
    def setUp(self):
        self.client = APIClient()
        
        # Create pharmacy owner
        self.owner = User.objects.create_user(
            email='owner@pharmacy.com',
            password='testpass123!',
            first_name='Pharmacy',
            last_name='Owner',
            role='PHARMACY_OWNER'
        )
        self.owner.is_verified = True
        self.owner.is_active = True
        self.owner.account_status = 'ACTIVE'
        self.owner.save()
        
        # Create pharmacy
        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Test Pharmacy Legal',
            brand_name='Test Pharmacy',
            verification_status='VERIFIED'
        )
        
        # Create unverified pharmacy
        self.unverified_pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Unverified Pharmacy',
            brand_name='Unverified Pharmacy',
            verification_status='PENDING_VERIFICATION'
        )
        
        # Create medicine
        admin = User.objects.create_user(
            email='admin@platform.com',
            password='testpass123!',
            role='PLATFORM_ADMIN'
        )
        admin.is_verified = True
        admin.is_active = True
        admin.save()
        
        self.medicine = Medicine.objects.create(
            generic_name='Paracetamol',
            strength='500mg',
            dosage_form='TABLET',
            created_by=admin
        )
    
    def test_owner_can_create_inventory_item(self):
        """Test that pharmacy owner can create inventory item"""
        self.client.force_authenticate(user=self.owner)
        
        payload = {
            'medicine': str(self.medicine.id),
            'selling_price': '3500.00',
            'status': 'ACTIVE'
        }
        
        response = self.client.post('/api/inventory/items/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        item = PharmacyInventoryItem.objects.get(pharmacy=self.pharmacy)
        self.assertEqual(item.medicine_id, self.medicine.id)
        self.assertEqual(item.selling_price, Decimal('3500.00'))
    
    def test_cannot_create_duplicate_inventory(self):
        """Test that duplicate pharmacy+medicine inventory is prevented"""
        # Create first inventory item
        PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy,
            medicine=self.medicine,
            selling_price=Decimal('3500.00')
        )
        
        self.client.force_authenticate(user=self.owner)
        
        payload = {
            'medicine': str(self.medicine.id),
            'selling_price': '3600.00',
            'status': 'ACTIVE'
        }
        
        response = self.client.post('/api/inventory/items/', payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_cannot_set_zero_price(self):
        """Test that zero or negative prices are rejected"""
        self.client.force_authenticate(user=self.owner)
        
        payload = {
            'medicine': str(self.medicine.id),
            'selling_price': '0.00',
            'status': 'ACTIVE'
        }
        
        response = self.client.post('/api/inventory/items/', payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class InventoryBatchTests(TestCase):
    """Test inventory batch creation and expiry tracking"""
    
    def setUp(self):
        self.client = APIClient()
        
        # Create pharmacy owner
        self.owner = User.objects.create_user(
            email='owner@pharmacy.com',
            password='testpass123!',
            role='PHARMACY_OWNER'
        )
        self.owner.is_verified = True
        self.owner.is_active = True
        self.owner.account_status = 'ACTIVE'
        self.owner.save()
        
        # Create verified pharmacy
        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Test Pharmacy',
            brand_name='Test Pharmacy',
            verification_status='VERIFIED'
        )
        
        # Create medicine
        admin = User.objects.create_user(
            email='admin@platform.com',
            password='testpass123!',
            role='PLATFORM_ADMIN'
        )
        admin.is_verified = True
        admin.is_active = True
        admin.save()
        
        self.medicine = Medicine.objects.create(
            generic_name='Paracetamol',
            strength='500mg',
            dosage_form='TABLET',
            created_by=admin
        )
        
        # Create inventory item
        self.inventory = PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy,
            medicine=self.medicine,
            selling_price=Decimal('3500.00')
        )
    
    def test_batch_quantity_cannot_be_negative(self):
        """Test that batch quantity cannot be negative"""
        self.client.force_authenticate(user=self.owner)
        
        future_date = timezone.now().date() + timedelta(days=365)
        
        payload = {
            'inventory_item_id': str(self.inventory.id),
            'batch_number': 'BATCH001',
            'quantity': -5,
            'expiry_date': future_date.isoformat()
        }
        
        response = self.client.post('/api/inventory/batches/', payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_batch_expiry_date_cannot_be_past(self):
        """Test that expiry date cannot be in the past"""
        self.client.force_authenticate(user=self.owner)
        
        past_date = timezone.now().date() - timedelta(days=1)
        
        payload = {
            'inventory_item_id': str(self.inventory.id),
            'batch_number': 'BATCH001',
            'quantity': 100,
            'expiry_date': past_date.isoformat()
        }
        
        response = self.client.post('/api/inventory/batches/', payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_multiple_batches_increase_total_quantity(self):
        """Test that multiple batches add up correctly"""
        future_date = timezone.now().date() + timedelta(days=365)
        
        # Create two batches
        InventoryBatch.objects.create(
            inventory_item=self.inventory,
            batch_number='BATCH001',
            quantity=100,
            expiry_date=future_date
        )
        
        InventoryBatch.objects.create(
            inventory_item=self.inventory,
            batch_number='BATCH002',
            quantity=150,
            expiry_date=future_date
        )
        
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.total_quantity, 250)
    
    def test_expired_batches_not_counted(self):
        """Test that expired batches are not included in total quantity"""
        future_date = timezone.now().date() + timedelta(days=365)
        past_date = timezone.now().date() - timedelta(days=1)
        
        # Create active batch
        InventoryBatch.objects.create(
            inventory_item=self.inventory,
            batch_number='BATCH001',
            quantity=100,
            expiry_date=future_date
        )
        
        # Create expired batch
        InventoryBatch.objects.create(
            inventory_item=self.inventory,
            batch_number='BATCH002',
            quantity=50,
            expiry_date=past_date
        )
        
        # Only active batch should be counted
        # Note: We need to check if expired batches exist, not in total
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.total_quantity, 100)
        self.assertTrue(self.inventory.has_expired_stock)


class InventoryPublicationTests(TestCase):
    """Test inventory publication workflow"""
    
    def setUp(self):
        self.client = APIClient()
        
        # Create pharmacy owner
        self.owner = User.objects.create_user(
            email='owner@pharmacy.com',
            password='testpass123!',
            role='PHARMACY_OWNER'
        )
        self.owner.is_verified = True
        self.owner.is_active = True
        self.owner.account_status = 'ACTIVE'
        self.owner.save()
        
        # Create verified pharmacy
        self.verified_pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Verified Pharmacy',
            brand_name='Verified Pharmacy',
            verification_status='VERIFIED'
        )
        
        # Create unverified pharmacy
        self.unverified_pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Unverified Pharmacy',
            brand_name='Unverified Pharmacy',
            verification_status='PENDING_VERIFICATION'
        )
        
        # Create medicine
        admin = User.objects.create_user(
            email='admin@platform.com',
            password='testpass123!',
            role='PLATFORM_ADMIN'
        )
        admin.is_verified = True
        admin.is_active = True
        admin.save()
        
        self.medicine = Medicine.objects.create(
            generic_name='Paracetamol',
            strength='500mg',
            dosage_form='TABLET',
            created_by=admin
        )
        
        # Create inventory item for verified pharmacy
        self.inventory_verified = PharmacyInventoryItem.objects.create(
            pharmacy=self.verified_pharmacy,
            medicine=self.medicine,
            selling_price=Decimal('3500.00'),
            status='ACTIVE'
        )
        
        # Create inventory item for unverified pharmacy
        self.inventory_unverified = PharmacyInventoryItem.objects.create(
            pharmacy=self.unverified_pharmacy,
            medicine=self.medicine,
            selling_price=Decimal('3500.00'),
            status='ACTIVE'
        )
        
        # Add batch with stock
        future_date = timezone.now().date() + timedelta(days=365)
        InventoryBatch.objects.create(
            inventory_item=self.inventory_verified,
            batch_number='BATCH001',
            quantity=100,
            expiry_date=future_date
        )
        
        InventoryBatch.objects.create(
            inventory_item=self.inventory_unverified,
            batch_number='BATCH001',
            quantity=100,
            expiry_date=future_date
        )
    
    def test_can_publish_verified_pharmacy_inventory(self):
        """Test that inventory of VERIFIED pharmacy can be published"""
        self.client.force_authenticate(user=self.owner)
        
        response = self.client.post(f'/api/inventory/items/{self.inventory_verified.id}/publish/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.inventory_verified.refresh_from_db()
        self.assertTrue(self.inventory_verified.is_published)
        self.assertIsNotNone(self.inventory_verified.published_at)
        self.assertEqual(self.inventory_verified.published_by_id, self.owner.id)
    
    def test_cannot_publish_unverified_pharmacy_inventory(self):
        """Test that inventory of unverified pharmacy CANNOT be published"""
        self.client.force_authenticate(user=self.owner)
        
        response = self.client.post(f'/api/inventory/items/{self.inventory_unverified.id}/publish/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        self.inventory_unverified.refresh_from_db()
        self.assertFalse(self.inventory_unverified.is_published)
    
    def test_can_unpublish_inventory(self):
        """Test that published inventory can be unpublished"""
        # First publish
        self.inventory_verified.publish(self.owner)
        self.assertTrue(self.inventory_verified.is_published)
        
        self.client.force_authenticate(user=self.owner)
        
        # Then unpublish
        response = self.client.post(f'/api/inventory/items/{self.inventory_verified.id}/unpublish/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.inventory_verified.refresh_from_db()
        self.assertFalse(self.inventory_verified.is_published)
    
    def test_cannot_publish_without_stock(self):
        """Test that inventory without stock cannot be published"""
        # Create inventory but don't add batches
        inventory_no_stock = PharmacyInventoryItem.objects.create(
            pharmacy=self.verified_pharmacy,
            medicine=self.medicine,
            selling_price=Decimal('3500.00'),
            status='ACTIVE'
        )
        
        self.client.force_authenticate(user=self.owner)
        
        response = self.client.post(f'/api/inventory/items/{inventory_no_stock.id}/publish/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_cannot_publish_inactive_item(self):
        """Test that inactive inventory cannot be published"""
        self.inventory_verified.status = 'INACTIVE'
        self.inventory_verified.save()
        
        self.client.force_authenticate(user=self.owner)
        
        response = self.client.post(f'/api/inventory/items/{self.inventory_verified.id}/publish/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CrossPharmacySecurityTests(TestCase):
    """Test that users cannot access/modify other pharmacy inventory"""
    
    def setUp(self):
        self.client = APIClient()
        
        # Create two pharmacy owners
        self.owner_a = User.objects.create_user(
            email='owner_a@pharmacy.com',
            password='testpass123!',
            role='PHARMACY_OWNER'
        )
        self.owner_a.is_verified = True
        self.owner_a.is_active = True
        self.owner_a.account_status = 'ACTIVE'
        self.owner_a.save()
        
        self.owner_b = User.objects.create_user(
            email='owner_b@pharmacy.com',
            password='testpass123!',
            role='PHARMACY_OWNER'
        )
        self.owner_b.is_verified = True
        self.owner_b.is_active = True
        self.owner_b.account_status = 'ACTIVE'
        self.owner_b.save()
        
        # Create pharmacies
        self.pharmacy_a = PharmacyBrand.objects.create(
            owner=self.owner_a,
            legal_name='Pharmacy A',
            brand_name='Pharmacy A',
            verification_status='VERIFIED'
        )
        
        self.pharmacy_b = PharmacyBrand.objects.create(
            owner=self.owner_b,
            legal_name='Pharmacy B',
            brand_name='Pharmacy B',
            verification_status='VERIFIED'
        )
        
        # Create medicine
        admin = User.objects.create_user(
            email='admin@platform.com',
            password='testpass123!',
            role='PLATFORM_ADMIN'
        )
        admin.is_verified = True
        admin.is_active = True
        admin.save()
        
        self.medicine = Medicine.objects.create(
            generic_name='Paracetamol',
            strength='500mg',
            dosage_form='TABLET',
            created_by=admin
        )
        
        # Create inventory for pharmacy A
        self.inventory_a = PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy_a,
            medicine=self.medicine,
            selling_price=Decimal('3500.00')
        )
    
    def test_owner_a_cannot_view_pharmacy_b_inventory(self):
        """Test that Owner A cannot see Pharmacy B's inventory"""
        # Create inventory for pharmacy B
        inventory_b = PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy_b,
            medicine=self.medicine,
            selling_price=Decimal('3600.00')
        )
        
        self.client.force_authenticate(user=self.owner_a)
        
        response = self.client.get(f'/api/inventory/items/{inventory_b.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_owner_a_cannot_modify_pharmacy_b_inventory(self):
        """Test that Owner A cannot modify Pharmacy B's inventory"""
        # Create inventory for pharmacy B
        inventory_b = PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy_b,
            medicine=self.medicine,
            selling_price=Decimal('3600.00')
        )
        
        self.client.force_authenticate(user=self.owner_a)
        
        payload = {'selling_price': '3700.00'}
        response = self.client.patch(f'/api/inventory/items/{inventory_b.id}/', payload)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_owner_a_can_only_see_own_pharmacy_inventory(self):
        """Test that Owner A can only list their own pharmacy inventory"""
        # Create inventory for pharmacy B
        inventory_b = PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy_b,
            medicine=self.medicine,
            selling_price=Decimal('3600.00')
        )
        
        self.client.force_authenticate(user=self.owner_a)
        
        response = self.client.get('/api/inventory/items/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], str(self.inventory_a.id))
