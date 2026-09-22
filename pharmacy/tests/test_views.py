from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from django.contrib.auth import get_user_model
from pharmacy.models import PharmacyBrand, PharmacyMembership

User = get_user_model()


class PharmacyViewsTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(email='owner@example.com', password='Pass1234', role='PHARMACY_OWNER', account_status='ACTIVE', is_verified=True, is_approved=True)
        self.staff = User.objects.create_user(email='staff@example.com', password='Pass1234', role='PHARMACY_STAFF', account_status='ACTIVE', is_verified=True)
        self.admin = User.objects.create_user(email='admin@example.com', password='Pass1234', role='SUPER_ADMIN', account_status='ACTIVE', is_verified=True, is_approved=True)

    def test_owner_can_create_pharmacy(self):
        self.client.force_authenticate(self.owner)
        url = reverse('pharmacybrand-list')
        data = {'legal_name': 'Test Ltd', 'brand_name': 'TestPharm', 'city': 'Lagos', 'state': 'Lagos'}
        r = self.client.post(url, data)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(PharmacyBrand.objects.count(), 1)
        self.assertIn('id', r.json())
        brand = PharmacyBrand.objects.first()
        self.assertEqual(brand.owner, self.owner)
        self.assertNotEqual(brand.verification_status, 'VERIFIED')

    def test_owner_cannot_create_duplicate_pharmacy_brand(self):
        PharmacyBrand.objects.create(owner=self.owner, legal_name='First Ltd', brand_name='First Pharmacy')
        self.client.force_authenticate(self.owner)
        response = self.client.post(reverse('pharmacybrand-list'), {
            'legal_name': 'Second Ltd',
            'brand_name': 'Second Pharmacy',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('detail', response.json())
        self.assertIn('already has a pharmacy brand', response.json()['detail'])
        self.assertEqual(PharmacyBrand.objects.filter(owner=self.owner).count(), 1)

    def test_create_converts_and_returns_geojson_location(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(reverse('pharmacybrand-list'), {
            'legal_name': 'Geo Ltd',
            'brand_name': 'Geo Pharmacy',
            'location': {'type': 'Point', 'coordinates': [3.3515, 6.6018]},
        }, format='json')

        self.assertEqual(response.status_code, 201)
        brand = PharmacyBrand.objects.get(brand_name='Geo Pharmacy')
        self.assertEqual(brand.location.srid, 4326)
        self.assertAlmostEqual(brand.location.x, 3.3515)
        self.assertEqual(response.json()['location'], {'type': 'Point', 'coordinates': [3.3515, 6.6018]})

    def test_invalid_location_is_rejected(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(reverse('pharmacybrand-list'), {
            'legal_name': 'Invalid Ltd',
            'brand_name': 'Invalid Pharmacy',
            'location': {'type': 'Point', 'coordinates': [181, 6]},
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('location', response.json())

    def test_brand_name_is_unique_case_insensitively_and_trimmed(self):
        self.client.force_authenticate(self.owner)
        url = reverse('pharmacybrand-list')
        first = self.client.post(url, {'legal_name': 'First Ltd', 'brand_name': ' HealthPlus Pharmacy '}, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(PharmacyBrand.objects.get().brand_name, 'HealthPlus Pharmacy')

        for name in ('HealthPlus Pharmacy', 'healthplus pharmacy', 'HEALTHPLUS PHARMACY', ' HealthPlus Pharmacy '):
            response = self.client.post(url, {'legal_name': 'Another Ltd', 'brand_name': name}, format='json')
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()['brand_name'][0], 'A pharmacy with this brand name already exists.')

    def test_non_owner_roles_and_client_owner_id_cannot_create(self):
        url = reverse('pharmacybrand-list')
        for role in ('PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF'):
            user = User.objects.create_user(email=f'{role.lower()}@example.com', password='Pass1234', role=role, account_status='ACTIVE', is_verified=True)
            self.client.force_authenticate(user)
            response = self.client.post(url, {
                'legal_name': 'Blocked Ltd',
                'brand_name': f'Blocked {role}',
                'owner': str(self.owner.id),
            }, format='json')
            self.assertEqual(response.status_code, 403)
        self.client.force_authenticate(self.owner)
        response = self.client.post(url, {
            'legal_name': 'Owned Ltd',
            'brand_name': 'Owned Pharmacy',
            'owner_id': str(self.staff.id),
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(PharmacyBrand.objects.get(brand_name='Owned Pharmacy').owner, self.owner)

    def test_my_pharmacy_uses_authenticated_owner_and_returns_pharmacy_id(self):
        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Mine Ltd',
            brand_name='Mine Pharmacy',
            verification_status='VERIFIED',
            pharmacy_id='CFS-PHARM-1234567890',
        )
        self.client.force_authenticate(self.owner)
        response = self.client.get(reverse('my-pharmacy'))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['id'], str(brand.id))
        self.assertIn('pharmacy_id', payload)
        self.assertEqual(payload['pharmacy_id'], brand.pharmacy_id)

        second = self.client.get(reverse('my-pharmacy'))
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['pharmacy_id'], brand.pharmacy_id)

    def test_manager_with_approved_membership_can_resolve_my_pharmacy(self):
        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Manager Brand Ltd',
            brand_name='Manager Brand Pharmacy',
            verification_status='VERIFIED',
            pharmacy_id='CFS-PHARM-0987654321',
        )
        manager = User.objects.create_user(
            email='manager@example.com',
            password='Pass1234',
            role='PHARMACY_MANAGER',
            account_status='ACTIVE',
            is_verified=True,
            is_approved=True,
        )
        PharmacyMembership.objects.create(
            user=manager,
            pharmacy=brand,
            role='PHARMACY_MANAGER',
            status='APPROVED',
        )

        self.client.force_authenticate(manager)
        response = self.client.get(reverse('my-pharmacy'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['id'], str(brand.id))
        self.assertEqual(response.json()['brand_name'], brand.brand_name)

    def test_manager_with_approved_membership_can_create_medicine_for_their_pharmacy(self):
        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Medicine Brand Ltd',
            brand_name='Medicine Brand Pharmacy',
            verification_status='VERIFIED',
            pharmacy_id='CFS-PHARM-1111111111',
        )
        manager = User.objects.create_user(
            email='medmanager@example.com',
            password='Pass1234',
            role='PHARMACY_MANAGER',
            account_status='ACTIVE',
            is_verified=True,
            is_approved=True,
        )
        PharmacyMembership.objects.create(
            user=manager,
            pharmacy=brand,
            role='PHARMACY_MANAGER',
            status='APPROVED',
        )

        self.client.force_authenticate(manager)
        response = self.client.post(
            reverse('pharmacy-medicines-list', args=[str(brand.id)]),
            {
                'generic_name': 'Amoxicillin',
                'brand_name': 'Moxifast',
                'strength': '500mg',
                'dosage_form': 'CAPSULE',
                'route': 'ORAL',
                'manufacturer': 'Care Plus',
                'pack_size': 12,
                'pack_size_unit': 'PACK',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['pharmacy'], str(brand.id))

    def test_platform_admin_can_approve_pharmacy_and_generate_pharmacy_id(self):
        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Platform Ltd',
            brand_name='Platform Pharmacy',
            verification_status='UNDER_REVIEW',
        )
        self.client.force_authenticate(self.admin)
        response = self.client.post(reverse('pharmacybrand-approve', args=[str(brand.id)]), format='json')
        self.assertEqual(response.status_code, 200)
        brand.refresh_from_db()
        self.assertTrue(brand.pharmacy_id.startswith('CFS-PHARM-'))
        self.assertEqual(len(brand.pharmacy_id), 20)
        self.assertEqual(response.json()['pharmacy_id'], brand.pharmacy_id)

    def test_non_owner_cannot_create_pharmacy(self):
        self.client.force_authenticate(self.staff)
        url = reverse('pharmacybrand-list')
        data = {'legal_name': 'Test Ltd', 'brand_name': 'TestPharm'}
        r = self.client.post(url, data)
        # Should be forbidden because create_pharmacy_brand checks role
        self.assertNotEqual(r.status_code, 201)

    def test_public_list_shows_only_verified(self):
        # create one verified and one pending
        b1 = PharmacyBrand.objects.create(owner=self.owner, legal_name='A', brand_name='A', city='C', state='S')
        b2 = PharmacyBrand.objects.create(owner=self.staff, legal_name='B', brand_name='B', city='C', state='S')
        b1.verification_status = 'VERIFIED'
        b1.save()
        url = reverse('pharmacybrand-list')
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(all(item['brand_name'] == 'A' for item in data))

    def test_pharmacy_search_url_resolves_and_filters_verified_only(self):
        verified = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='MixaGrip Health Ltd',
            brand_name='MixaGrip Pharmacy',
            city='Lagos',
            state='Lagos'
        )
        verified.verification_status = 'VERIFIED'
        verified.save()

        pending = PharmacyBrand.objects.create(
            owner=self.staff,
            legal_name='MixaGrip Pending Ltd',
            brand_name='MixaGrip Pharmacy Pending',
            city='Abuja',
            state='FCT'
        )
        pending.verification_status = 'PENDING_VERIFICATION'
        pending.save()

        url = reverse('pharmacy-search')
        response = self.client.get(url, {'q': 'mixagrip'})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        names = [item['brand_name'] for item in payload]
        self.assertIn('MixaGrip Pharmacy', names)
        self.assertNotIn('MixaGrip Pharmacy Pending', names)

    def test_pharmacy_search_without_query_returns_verified_brands(self):
        verified = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Verified Clinic',
            brand_name='Verified Clinic Brand',
            city='Ibadan',
            state='Oyo'
        )
        verified.verification_status = 'VERIFIED'
        verified.save()

        pending = PharmacyBrand.objects.create(
            owner=self.staff,
            legal_name='Pending Clinic',
            brand_name='Pending Clinic Brand',
            city='Kaduna',
            state='Kaduna'
        )
        pending.verification_status = 'UNDER_REVIEW'
        pending.save()

        response = self.client.get(reverse('pharmacy-search'))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        names = [item['brand_name'] for item in payload]
        self.assertIn('Verified Clinic Brand', names)
        self.assertNotIn('Pending Clinic Brand', names)

    def test_employee_can_request_membership_for_verified_pharmacy(self):
        b1 = PharmacyBrand.objects.create(owner=self.owner, legal_name='A', brand_name='A', city='C', state='S')
        b1.verification_status = 'VERIFIED'
        b1.save()
        self.client.force_authenticate(self.staff)
        url = reverse('pharmacymembership-list')
        data = {'pharmacy': str(b1.id), 'role': 'PHARMACY_STAFF'}
        r = self.client.post(url, data)
        # serializer returns 201 or 200 depending on viewset; ensure a membership is created
        self.assertIn(r.status_code, (200, 201))
        self.assertEqual(PharmacyMembership.objects.count(), 1)

    def test_owner_can_view_and_approve_membership(self):
        b1 = PharmacyBrand.objects.create(owner=self.owner, legal_name='A', brand_name='A', city='C', state='S')
        b1.verification_status = 'VERIFIED'
        b1.save()
        # staff requests membership
        self.client.force_authenticate(self.staff)
        url = reverse('pharmacymembership-list')
        data = {'pharmacy': str(b1.id), 'role': 'PHARMACY_STAFF'}
        r = self.client.post(url, data)
        self.assertIn(r.status_code, (200, 201))
        membership = PharmacyMembership.objects.first()
        # owner views requests
        self.client.force_authenticate(self.owner)
        req_url = reverse('pharmacybrand-membership-requests', args=[str(b1.id)])
        r2 = self.client.get(req_url)
        self.assertEqual(r2.status_code, 200)
        # owner approves membership
        approve_url = reverse('pharmacymembership-approve', args=[str(membership.id)])
        r3 = self.client.post(approve_url)
        self.assertEqual(r3.status_code, 200)
        membership.refresh_from_db()
        self.assertEqual(membership.status, 'APPROVED')

    def test_pharmacy_id_is_generated_only_after_approval(self):
        from pharmacy.services import approve_pharmacy_brand

        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Approval Ltd',
            brand_name='Approval Pharmacy',
            verification_status='UNDER_REVIEW',
        )
        self.assertIsNone(brand.pharmacy_id)
        approve_pharmacy_brand(brand, self.admin)
        brand.refresh_from_db()
        self.assertTrue(brand.pharmacy_id.startswith('CFS-PHARM-'))
        self.assertEqual(len(brand.pharmacy_id), 20)

    def test_verified_brand_without_pharmacy_id_is_backfilled(self):
        from pharmacy.services import repair_missing_pharmacy_ids

        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Backfill Ltd',
            brand_name='Backfill Pharmacy',
            verification_status='VERIFIED',
            verified_by=self.admin,
            verified_at=None,
        )

        self.assertIsNone(brand.pharmacy_id)

        repair_missing_pharmacy_ids()

        brand.refresh_from_db()
        self.assertTrue(brand.pharmacy_id.startswith('CFS-PHARM-'))
        self.assertEqual(len(brand.pharmacy_id), 20)

    def test_employee_can_lookup_and_request_with_pharmacy_id(self):
        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Join Ltd',
            brand_name='Join Pharmacy',
            city='Kano',
            state='Kano',
            verification_status='VERIFIED',
            pharmacy_id='CFS-PHARM-1234567890',
        )
        self.client.force_authenticate(self.staff)
        lookup = self.client.post(reverse('pharmacy-join-lookup'), {'pharmacy_id': brand.pharmacy_id}, format='json')
        self.assertEqual(lookup.status_code, 200)
        self.assertEqual(lookup.json()['brand_name'], 'Join Pharmacy')
        self.assertNotIn('owner', lookup.json())

        request = self.client.post(reverse('pharmacy-join-request'), {'pharmacy_id': brand.pharmacy_id}, format='json')
        self.assertEqual(request.status_code, 201)
        membership = PharmacyMembership.objects.get(user=self.staff, pharmacy=brand)
        self.assertEqual(membership.status, 'PENDING')
        self.assertEqual(membership.role, 'PHARMACY_STAFF')

        duplicate = self.client.post(reverse('pharmacy-join-request'), {'pharmacy_id': brand.pharmacy_id}, format='json')
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn('pending request', duplicate.json()['detail'])

    def test_join_lookup_rejects_unapproved_and_platform_users(self):
        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Pending Ltd',
            brand_name='Pending Join Pharmacy',
            verification_status='PENDING_VERIFICATION',
            pharmacy_id='CFS-PHARM-0987654321',
        )
        self.client.force_authenticate(self.staff)
        invalid = self.client.post(reverse('pharmacy-join-lookup'), {'pharmacy_id': brand.pharmacy_id}, format='json')
        self.assertEqual(invalid.status_code, 404)

        self.client.force_authenticate(self.admin)
        forbidden = self.client.post(reverse('pharmacy-join-lookup'), {'pharmacy_id': brand.pharmacy_id}, format='json')
        self.assertEqual(forbidden.status_code, 403)

    def test_owner_can_regenerate_id_without_removing_memberships(self):
        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Regenerate Ltd',
            brand_name='Regenerate Pharmacy',
            verification_status='VERIFIED',
            pharmacy_id='CFS-PHARM-ABCDEFGHIJ',
        )
        membership = PharmacyMembership.objects.create(
            user=self.staff,
            pharmacy=brand,
            role='PHARMACY_STAFF',
            status='APPROVED',
        )
        self.client.force_authenticate(self.owner)
        response = self.client.post(reverse('pharmacybrand-regenerate-pharmacy-id'), format='json')
        self.assertEqual(response.status_code, 200)
        brand.refresh_from_db()
        self.assertNotEqual(brand.pharmacy_id, 'CFS-PHARM-ABCDEFGHIJ')
        self.assertTrue(PharmacyMembership.objects.filter(pk=membership.pk, status='APPROVED').exists())