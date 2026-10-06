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

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase
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
        """Test that PLATFORM_ADMIN creates medicines through the admin catalog endpoint."""
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

        response = self.client.post('/api/medicine/admin/medicines/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['source'], 'ADMIN')

        medicine = Medicine.objects.get(generic_name='Paracetamol')
        self.assertEqual(medicine.brand_name, 'Panadol')
        self.assertEqual(medicine.created_by_id, self.admin.id)
        self.assertEqual(medicine.source, 'ADMIN')
    
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

    def test_global_medicine_duplicate_prevention_across_pharmacies(self):
        """The same medicine should not be duplicated across different pharmacies."""
        first_pharmacy = PharmacyBrand.objects.create(
            owner=User.objects.create_user(
                email='owner1@pharmacy.com',
                password='testpass123!',
                first_name='Owner',
                last_name='One',
                role='PHARMACY_OWNER',
            ),
            legal_name='Pharmacy One',
            brand_name='Pharmacy One',
            verification_status='VERIFIED',
        )
        second_pharmacy = PharmacyBrand.objects.create(
            owner=User.objects.create_user(
                email='owner2@pharmacy.com',
                password='testpass123!',
                first_name='Owner',
                last_name='Two',
                role='PHARMACY_OWNER',
            ),
            legal_name='Pharmacy Two',
            brand_name='Pharmacy Two',
            verification_status='VERIFIED',
        )

        first_medicine, first_created = Medicine.get_or_create_global(
            created_by=first_pharmacy.owner,
            created_by_pharmacy=first_pharmacy,
            source='PHARMACY',
            generic_name='Paracetamol',
            brand_name='Panadol',
            strength='500mg',
            dosage_form='TABLET',
            route='ORAL',
            manufacturer='Acme Pharma',
        )

        second_medicine, second_created = Medicine.get_or_create_global(
            created_by=second_pharmacy.owner,
            created_by_pharmacy=second_pharmacy,
            source='PHARMACY',
            generic_name='Paracetamol',
            brand_name='Panadol',
            strength='500mg',
            dosage_form='TABLET',
            route='ORAL',
            manufacturer='Acme Pharma',
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first_medicine.pk, second_medicine.pk)
        self.assertEqual(
            Medicine.objects.filter(
                generic_name='Paracetamol',
                brand_name='Panadol',
                strength='500mg',
                dosage_form='TABLET',
                route='ORAL',
                manufacturer='Acme Pharma',
            ).count(),
            1,
        )

    def test_database_constraint_blocks_direct_equivalent_duplicate(self):
        fields = {
            'generic_name': 'Metformin',
            'brand_name': 'Glucophage',
            'strength': '500mg',
            'dosage_form': 'TABLET',
            'route': 'ORAL',
            'manufacturer': 'Acme',
            'pack_size': 30,
            'pack_size_unit': 'PACK',
        }
        Medicine.objects.create(**fields)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Medicine.objects.create(
                    **{
                        **fields,
                        'generic_name': ' metformin ',
                        'strength': '500 mg',
                        'manufacturer': ' acme ',
                    }
                )

    def test_medicine_model_has_no_pharmacy_ownership_field(self):
        field_names = {field.name for field in Medicine._meta.fields}

        self.assertNotIn('pharmacy', field_names)
        self.assertIn('created_by_pharmacy', field_names)
    
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
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['generic_name'], 'Ibuprofen')
    
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


class MedicineApiContractTests(TestCase):
    """Tests for the global catalog API contract and provenance safety."""

    def setUp(self):
        self.client = APIClient()

        self.admin = User.objects.create_user(
            email='api-admin@platform.com',
            password='testpass123!',
            first_name='Api',
            last_name='Admin',
            role='PLATFORM_ADMIN',
        )
        self.admin.is_verified = True
        self.admin.is_active = True
        self.admin.save()

        self.owner = User.objects.create_user(
            email='api-owner@pharmacy.com',
            password='testpass123!',
            first_name='Api',
            last_name='Owner',
            role='PHARMACY_OWNER',
        )
        self.owner.is_verified = True
        self.owner.is_active = True
        self.owner.save()

        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='API Pharmacy Legal',
            brand_name='API Pharmacy',
            verification_status='VERIFIED',
        )

        self.other_owner = User.objects.create_user(
            email='api-other-owner@pharmacy.com',
            password='testpass123!',
            role='PHARMACY_OWNER',
        )
        self.other_pharmacy = PharmacyBrand.objects.create(
            owner=self.other_owner,
            legal_name='Other API Pharmacy Legal',
            brand_name='Other API Pharmacy',
            verification_status='VERIFIED',
        )

    def test_pharmacy_create_response_hides_admin_provenance_fields(self):
        """Pharmacy create must return the pharmacy-safe catalog representation."""
        self.client.force_authenticate(user=self.owner)

        payload = {
            'generic_name': 'Amoxicillin',
            'brand_name': 'Amoxil',
            'strength': '500mg',
            'dosage_form': 'CAPSULE',
            'route': 'ORAL',
            'manufacturer': 'Pharma API',
            'pack_size': 12,
            'pack_size_unit': 'UNIT',
            'source': 'ADMIN',
            'created_by': str(self.admin.id),
            'created_by_pharmacy': str(self.other_pharmacy.id),
            'creator_role': 'PLATFORM_ADMIN',
        }

        response = self.client.post('/api/medicine/medicines/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('generic_name', response.data)
        self.assertNotIn('source', response.data)
        self.assertNotIn('created_by', response.data)
        self.assertNotIn('creator_role', response.data)
        self.assertNotIn('creator_pharmacy', response.data)
        self.assertNotIn('verification_status', response.data)

        medicine = Medicine.objects.get(generic_name='Amoxicillin')
        self.assertEqual(medicine.source, 'PHARMACY')
        self.assertEqual(medicine.created_by_id, self.owner.id)
        self.assertEqual(medicine.created_by_pharmacy, self.pharmacy)

    def test_admin_create_endpoint_assigns_admin_provenance(self):
        """Platform admins must create via the dedicated admin endpoint."""
        self.client.force_authenticate(user=self.admin)

        payload = {
            'generic_name': 'Cefuroxime',
            'brand_name': 'Zinacef',
            'strength': '250mg',
            'dosage_form': 'TABLET',
            'route': 'ORAL',
            'manufacturer': 'Platform Pharma',
            'pack_size': 10,
            'pack_size_unit': 'PACK',
            'source': 'PHARMACY',
            'created_by': str(self.owner.id),
            'created_by_pharmacy': str(self.pharmacy.id),
        }

        response = self.client.post('/api/medicine/admin/medicines/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['source'], 'ADMIN')
        self.assertEqual(response.data['created_by'], self.admin.id)

        medicine = Medicine.objects.get(id=response.data['id'])
        self.assertEqual(medicine.source, 'ADMIN')
        self.assertEqual(medicine.created_by_id, self.admin.id)
        self.assertIsNone(medicine.created_by_pharmacy_id)

    def test_non_admin_cannot_create_via_admin_endpoint(self):
        """Only platform admins may use the admin creation API."""
        self.client.force_authenticate(user=self.owner)

        payload = {
            'generic_name': 'Clarithromycin',
            'strength': '500mg',
            'dosage_form': 'TABLET',
            'route': 'ORAL',
            'manufacturer': 'Owner Pharma',
        }

        response = self.client.post('/api/medicine/admin/medicines/', payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_pharmacy_source_spoofing_is_rejected(self):
        """Client-controlled source values must not impersonate admin provenance."""
        self.client.force_authenticate(user=self.owner)

        payload = {
            'generic_name': 'Azithromycin',
            'brand_name': 'Zithromax',
            'strength': '250mg',
            'dosage_form': 'TABLET',
            'route': 'ORAL',
            'manufacturer': 'Spoof Pharma',
            'source': 'ADMIN',
        }

        response = self.client.post('/api/medicine/medicines/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        medicine = Medicine.objects.get(generic_name='Azithromycin')
        self.assertEqual(medicine.source, 'PHARMACY')
        self.assertNotEqual(medicine.source, 'ADMIN')

    def test_duplicate_submission_reuses_normalized_global_medicine(self):
        self.client.force_authenticate(user=self.owner)
        payload = {
            'generic_name': 'Ibuprofen',
            'brand_name': 'Relief',
            'strength': '200mg',
            'dosage_form': 'TABLET',
            'route': 'ORAL',
            'manufacturer': 'Acme Pharma',
            'pack_size': 10,
            'pack_size_unit': 'PACK',
        }

        first = self.client.post('/api/medicine/medicines/', payload)
        duplicate = self.client.post('/api/medicine/medicines/', {
            **payload,
            'generic_name': '  IBUPROFEN ',
            'strength': '200 mg',
            'manufacturer': ' acme   pharma ',
        })

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(duplicate.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first.data['id'], duplicate.data['id'])
        self.assertEqual(Medicine.objects.filter(generic_name__iexact='ibuprofen').count(), 1)

    def test_pharmacy_search_is_global_and_pharmacy_cannot_edit_catalog(self):
        medicine, _ = Medicine.get_or_create_global(
            created_by=self.admin,
            source='ADMIN',
            generic_name='GlobalSearchMedicine',
            brand_name='',
            strength='500mg',
            dosage_form='TABLET',
            route='ORAL',
            manufacturer='',
        )
        self.client.force_authenticate(user=self.owner)

        search = self.client.get('/api/medicine/medicines/search/?q=globalsearchmedicine')
        update = self.client.patch(
            f'/api/medicine/medicines/{medicine.id}/',
            {'strength': '650mg'},
        )

        self.assertEqual(search.status_code, status.HTTP_200_OK)
        self.assertEqual([row['id'] for row in search.data], [str(medicine.id)])
        self.assertEqual(update.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_admin_can_update_global_medicine_without_changing_provenance(self):
        self.client.force_authenticate(user=self.admin)
        created = self.client.post('/api/medicine/admin/medicines/', {
            'generic_name': 'Cefalexin',
            'brand_name': 'Keflex',
            'strength': '250mg',
            'dosage_form': 'CAPSULE',
            'route': 'ORAL',
            'manufacturer': 'Acme',
        })
        medicine_id = created.data['id']

        updated = self.client.patch(
            f'/api/medicine/admin/medicines/{medicine_id}/',
            {'strength': '500mg', 'source': 'PHARMACY', 'created_by': str(self.owner.id)},
        )

        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.data['strength'], '500mg')
        self.assertEqual(updated.data['source'], 'ADMIN')
        self.assertEqual(updated.data['created_by'], self.admin.id)

    def test_same_global_medicine_can_be_in_two_isolated_pharmacy_inventories(self):
        from inventory.models import PharmacyInventoryItem

        medicine = Medicine.objects.create(
            generic_name='Shared catalog item',
            brand_name='',
            strength='100mg',
            dosage_form='TABLET',
            route='ORAL',
        )
        inventory_a = PharmacyInventoryItem.objects.create(
            pharmacy=self.pharmacy,
            medicine=medicine,
            selling_price=Decimal('10.00'),
        )
        inventory_b = PharmacyInventoryItem.objects.create(
            pharmacy=self.other_pharmacy,
            medicine=medicine,
            selling_price=Decimal('20.00'),
        )
        self.client.force_authenticate(user=self.owner)

        response = self.client.get('/api/inventory/items/')

        self.assertEqual(inventory_a.medicine_id, inventory_b.medicine_id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row['id'] for row in response.data], [str(inventory_a.id)])
        self.assertEqual(response.data[0]['medicine_id'], str(medicine.id))

    def test_pharmacy_manager_requires_approved_membership_and_selected_pharmacy(self):
        manager = User.objects.create_user(
            email='api-manager@pharmacy.com',
            password='testpass123!',
            role='PHARMACY_MANAGER',
        )
        PharmacyMembership.objects.create(
            pharmacy=self.pharmacy,
            user=manager,
            role='PHARMACY_MANAGER',
            status='APPROVED',
            approved_by=self.owner,
        )
        self.client.force_authenticate(user=manager)
        response = self.client.post('/api/medicine/medicines/', {
            'generic_name': 'Manager submitted item',
            'brand_name': '',
            'strength': '5mg',
            'dosage_form': 'TABLET',
        })

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        medicine = Medicine.objects.get(generic_name='Manager submitted item')
        self.assertEqual(medicine.created_by_id, manager.id)
        self.assertEqual(medicine.created_by_pharmacy_id, self.pharmacy.id)


class GreenbookImportServiceTests(TestCase):
    """Tests for controlled Greenbook data import into the global medicine catalog."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='greenbook-admin@platform.com',
            password='testpass123!',
            first_name='Greenbook',
            last_name='Admin',
            role='PLATFORM_ADMIN',
        )
        self.admin.is_verified = True
        self.admin.is_active = True
        self.admin.save()

        self.owner = User.objects.create_user(
            email='greenbook-owner@pharmacy.com',
            password='testpass123!',
            first_name='Greenbook',
            last_name='Owner',
            role='PHARMACY_OWNER',
        )
        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Greenbook Pharmacy',
            brand_name='Greenbook Pharmacy',
            verification_status='VERIFIED',
        )

    def test_greenbook_csv_import_creates_public_database_records(self):
        from medicine.services import GreenbookImportService

        csv_content = """product_name,active_ingredients,product_category,form,route,strengths,nrn,applicant_name,approval_date,status
Panadol,Paracetamol,Analgesic,TABLET,ORAL,500mg,NRN-1001,Acme Pharma,2024-01-05,APPROVED
"""

        with self.settings(ALLOWED_HOSTS=['*']):
            with open('/tmp/greenbook-test.csv', 'w', encoding='utf-8') as handle:
                handle.write(csv_content)

            result = GreenbookImportService().import_file('/tmp/greenbook-test.csv')

        self.assertEqual(result.created, 1)
        self.assertEqual(result.rows_read, 1)
        self.assertEqual(Medicine.objects.filter(source='PUBLIC_DATABASE').count(), 1)
        medicine = Medicine.objects.get(source='PUBLIC_DATABASE')
        self.assertEqual(medicine.generic_name, 'Paracetamol')
        self.assertEqual(medicine.brand_name, 'Panadol')
        self.assertEqual(medicine.strength, '500mg')
        self.assertEqual(medicine.nafdac_registration, 'NRN-1001')

    def test_greenbook_import_is_idempotent_for_duplicate_rows(self):
        from medicine.services import GreenbookImportService

        records = [{
            'product_name': 'Amoxicillin 500mg Capsule',
            'active_ingredients': 'Amoxicillin',
            'form': 'CAPSULE',
            'route': 'ORAL',
            'strengths': '500mg',
            'nrn': 'NRN-2002',
            'applicant_name': 'Alpha Pharma',
        }]

        first = GreenbookImportService().import_records(records)
        second = GreenbookImportService().import_records(records)

        self.assertEqual(first.created, 1)
        self.assertEqual(second.created, 0)
        self.assertEqual(Medicine.objects.filter(source='PUBLIC_DATABASE').count(), 1)

    def test_greenbook_dry_run_does_not_write_database(self):
        from medicine.services import GreenbookImportService

        records = [{
            'product_name': 'Ibuprofen 200mg Tablet',
            'active_ingredients': 'Ibuprofen',
            'form': 'TABLET',
            'route': 'ORAL',
            'strengths': '200mg',
            'nrn': 'NRN-3003',
            'applicant_name': 'Beta Pharma',
        }]

        result = GreenbookImportService().import_records(records, dry_run=True)

        self.assertEqual(result.created, 1)
        self.assertEqual(Medicine.objects.count(), 0)
        self.assertEqual(result.matched, 0)

    def test_greenbook_import_preserves_existing_pharmacy_provenance(self):
        from medicine.services import GreenbookImportService

        medicine = Medicine.objects.create(
            generic_name='Amoxicillin',
            brand_name='Amoxil',
            strength='500mg',
            dosage_form='CAPSULE',
            route='ORAL',
            manufacturer='Local Lab',
            created_by=self.owner,
            created_by_pharmacy=self.pharmacy,
            source='PHARMACY',
        )

        result = GreenbookImportService().import_records([{
            'product_name': 'Amoxil',
            'active_ingredients': 'Amoxicillin',
            'form': 'CAPSULE',
            'route': 'ORAL',
            'strengths': '500mg',
            'nrn': 'NRN-4004',
            'applicant_name': 'Public Registry Lab',
        }])

        medicine.refresh_from_db()
        self.assertEqual(result.matched, 1)
        self.assertEqual(medicine.source, 'PHARMACY')
        self.assertEqual(medicine.created_by_pharmacy_id, self.pharmacy.id)
        self.assertEqual(medicine.created_by_id, self.owner.id)
        self.assertEqual(medicine.nafdac_registration, 'NRN-4004')

    def test_greenbook_import_reports_malformed_rows(self):
        from medicine.services import GreenbookImportService

        result = GreenbookImportService().import_records([
            {'product_name': 'Broken', 'form': 'TABLET', 'route': 'ORAL', 'strengths': '500mg'},
        ])

        self.assertEqual(result.errors, 1)
        self.assertIn('missing required fields', str(result.messages[0]).lower())


class ConcurrentMedicineCreationTests(TransactionTestCase):
    """Database-level duplicate protection for simultaneous catalog creation."""

    reset_sequences = True

    def setUp(self):
        self.owner = User.objects.create_user(
            email='concurrent-owner@pharmacy.com',
            password='testpass123!',
            role='PHARMACY_OWNER',
        )
        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Concurrent Pharmacy Legal',
            brand_name='Concurrent Pharmacy',
            verification_status='VERIFIED',
        )
        self.barrier = Barrier(2)
        self.fields = {
            'generic_name': 'Concurrent medicine',
            'brand_name': 'RaceTest',
            'strength': '50mg',
            'dosage_form': 'TABLET',
            'route': 'ORAL',
            'manufacturer': 'Cafsule Test',
            'pack_size': 10,
            'pack_size_unit': 'PACK',
        }

    def create_same_medicine(self):
        try:
            self.barrier.wait(timeout=10)
            return Medicine.get_or_create_global(
                created_by=self.owner,
                created_by_pharmacy=self.pharmacy,
                source='PHARMACY',
                **self.fields,
            )
        finally:
            connections.close_all()

    def test_concurrent_equivalent_submissions_create_one_catalog_record(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.create_same_medicine) for _ in range(2)]
            results = [future.result(timeout=30) for future in futures]

        self.assertEqual(Medicine.objects.filter(generic_name='Concurrent medicine').count(), 1)
        self.assertEqual(len({medicine.id for medicine, _ in results}), 1)
        self.assertEqual(sum(created for _, created in results), 1)


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
