from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from .models import PharmacyBrand, PharmacyBrandImage, PharmacyVerificationHistory
from .services import submit_pharmacy_brand, start_pharmacy_review, approve_pharmacy_brand, reject_pharmacy_brand, suspend_pharmacy_brand
from .views import PharmacyBrandViewSet


class PharmacyBrandDomainTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            email='owner@example.com',
            password='StrongPass123!',
            role='PHARMACY_OWNER',
            account_status='ACTIVE',
            is_verified=True,
            is_approved=True,
        )

    def test_pharmacy_brand_tracks_nigerian_business_details(self):
        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Grace Care Pharmacy Limited',
            brand_name='GraceCare Pharmacy',
            business_email='hello@gracecarepharmacy.com',
            business_phone='+2348000000000',
            address_line_1='10 Allen Avenue',
            address_line_2='Suite 3',
            city='Ikeja',
            state='Lagos',
            lga='Ikeja',
            country='Nigeria',
            postal_code='100271',
            cac_registration_number='RC1234567',
            cac_registration_type='Private Limited Company',
            pcn_premises_registration_number='PCN/LA/12345',
            pcn_license_number='PCN-98765',
            nafdac_registration_number='NAFDAC-223344',
            pharmacy_type='COMMUNITY_PHARMACY',
            years_in_operation=5,
        )

        try:
            from django.contrib.gis.geos import Point
            brand.location = Point(float('3.3515'), float('6.6018'))
            brand.save(update_fields=['location', 'updated_at'])
        except Exception:
            pass

        self.assertEqual(brand.owner, self.owner)
        self.assertEqual(brand.city, 'Ikeja')
        self.assertEqual(brand.state, 'Lagos')
        self.assertEqual(brand.nafdac_registration_number, 'NAFDAC-223344')
        self.assertEqual(brand.pharmacy_type, 'COMMUNITY_PHARMACY')

    def test_pharmacy_brand_image_can_be_created_for_brand(self):
        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Liberty Health Pharmacy',
            brand_name='Liberty Health',
            city='Abuja',
            state='FCT',
            lga='Garki',
        )

        image = PharmacyBrandImage.objects.create(
            brand=brand,
            image='brands/liberty-front.jpg',
            image_type='FRONT_VIEW',
            caption='Main pharmacy frontage',
            is_primary=True,
        )

        self.assertEqual(image.brand, brand)
        self.assertTrue(image.is_primary)
        self.assertEqual(image.image_type, 'FRONT_VIEW')

    def test_incomplete_brand_cannot_be_submitted(self):
        brand = PharmacyBrand.objects.create(owner=self.owner, legal_name='A', brand_name='A')
        with self.assertRaisesMessage(ValueError, 'Missing required information'):
            submit_pharmacy_brand(brand, self.owner)
        brand.refresh_from_db()
        self.assertEqual(brand.verification_status, 'DRAFT')

    def test_complete_brand_submission_creates_history(self):
        brand = PharmacyBrand.objects.create(
            owner=self.owner, legal_name='A', brand_name='A', address_line_1='1 Main St', state='Lagos',
            cac_registration_number='RC1', pcn_premises_registration_number='PCN1', location='3.3 6.6',
        )
        for image_type in ('EXTERIOR', 'INTERIOR'):
            for index in range(2):
                PharmacyBrandImage.objects.create(brand=brand, image=f'{image_type}-{index}.jpg', image_type=image_type)
        submit_pharmacy_brand(brand, self.owner)
        brand.refresh_from_db()
        self.assertEqual(brand.verification_status, 'PENDING_VERIFICATION')
        self.assertEqual(brand.verification_history.get().action, 'SUBMITTED')

    def test_verification_transitions_are_audited(self):
        admin = get_user_model().objects.create_user(email='admin@example.com', password='x', role='PLATFORM_ADMIN')
        brand = PharmacyBrand.objects.create(owner=self.owner, legal_name='A', brand_name='A', verification_status='PENDING_VERIFICATION')
        start_pharmacy_review(brand, admin)
        approve_pharmacy_brand(brand, admin)
        brand.refresh_from_db()
        self.assertEqual(brand.verified_by, admin)
        self.assertIsNotNone(brand.verified_at)
        self.assertEqual(list(brand.verification_history.values_list('previous_status', 'new_status')), [('PENDING_VERIFICATION', 'UNDER_REVIEW'), ('UNDER_REVIEW', 'VERIFIED')])

    def test_rejection_and_suspension_require_reasons(self):
        admin = get_user_model().objects.create_user(email='admin2@example.com', password='x', role='PLATFORM_ADMIN')
        brand = PharmacyBrand.objects.create(owner=self.owner, legal_name='A', brand_name='A', verification_status='UNDER_REVIEW')
        with self.assertRaisesMessage(ValueError, 'rejection reason'):
            reject_pharmacy_brand(brand, admin)
        brand.verification_status = 'VERIFIED'
        brand.save(update_fields=['verification_status'])
        with self.assertRaisesMessage(ValueError, 'suspension reason'):
            suspend_pharmacy_brand(brand, admin)

    def test_submitted_brand_remains_unapproved_until_platform_verification(self):
        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Cafsule Care Pharmacy',
            brand_name='Cafsule Care',
            address_line_1='13 Broad Street',
            state='Lagos',
            city='Lagos',
            lga='Surulere',
            cac_registration_number='RC1000',
            pcn_premises_registration_number='PCN-1000',
            location='3.33 6.52',
        )
        pharmacy_brand_images = [
            PharmacyBrandImage.objects.create(brand=brand, image='front-1.jpg', image_type='EXTERIOR'),
            PharmacyBrandImage.objects.create(brand=brand, image='front-2.jpg', image_type='EXTERIOR'),
            PharmacyBrandImage.objects.create(brand=brand, image='inside-1.jpg', image_type='INTERIOR'),
            PharmacyBrandImage.objects.create(brand=brand, image='inside-2.jpg', image_type='INTERIOR'),
        ]
        self.assertEqual(pharmacy_brand_images[0].brand, brand)

        submit_pharmacy_brand(brand, self.owner)
        brand.refresh_from_db()

        self.assertEqual(brand.verification_status, 'PENDING_VERIFICATION')
        self.assertFalse(brand.is_verified)
        self.assertIsNone(brand.pharmacy_id)

    def test_platform_approval_generates_pharmacy_id_and_marks_brand_verified(self):
        admin = get_user_model().objects.create_user(email='platform-admin@example.com', password='x', role='PLATFORM_ADMIN')
        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Unity Pharmacy Ltd',
            brand_name='Unity Pharmacy',
            address_line_1='7 Lekki Expressway',
            state='Lagos',
            city='Lekki',
            lga='Eti-Osa',
            cac_registration_number='RC2000',
            pcn_premises_registration_number='PCN-2000',
            verification_status='PENDING_VERIFICATION',
        )

        approve_pharmacy_brand(brand, admin)
        brand.refresh_from_db()

        self.assertEqual(brand.verification_status, 'VERIFIED')
        self.assertTrue(brand.is_verified)
        self.assertTrue(brand.pharmacy_id.startswith('CFS-PHARM-'))

    def test_unapproved_owner_cannot_access_pharmacy_workspace_id(self):
        factory = APIRequestFactory()
        brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Owner Test Pharmacy',
            brand_name='Owner Test',
            address_line_1='4 Victoria Island',
            state='Lagos',
            city='Victoria Island',
            lga='Lagos Island',
            cac_registration_number='RC3000',
            pcn_premises_registration_number='PCN-3000',
            verification_status='PENDING_VERIFICATION',
        )

        request = factory.post('/api/pharmacy/brands/my-pharmacy-id/')
        force_authenticate(request, user=self.owner)
        response = PharmacyBrandViewSet.as_view({'post': 'my_pharmacy_id'})(request)

        self.assertEqual(response.status_code, 404)
        self.assertIn('Pharmacy ID is available after pharmacy approval', response.data.get('detail', ''))

        brand.verification_status = 'VERIFIED'
        brand.pharmacy_id = 'CFS-PHARM-ABCDEFGHJK'
        brand.save(update_fields=['verification_status', 'pharmacy_id'])

        request = factory.post('/api/pharmacy/brands/my-pharmacy-id/')
        force_authenticate(request, user=self.owner)
        response = PharmacyBrandViewSet.as_view({'post': 'my_pharmacy_id'})(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['pharmacy_id'], 'CFS-PHARM-ABCDEFGHJK')


class PharmacyMembershipTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            email='owner2@example.com',
            password='StrongPass123!',
            role='PHARMACY_OWNER',
            account_status='ACTIVE',
            is_verified=True,
            is_approved=True,
        )
        self.brand = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Test Pharmacy',
            brand_name='TestPharm',
            city='Lagos',
            state='Lagos',
        )

    def test_employee_membership_request_and_approval(self):
        employee = get_user_model().objects.create_user(
            email='staff@example.com',
            password='Password123',
            role='PHARMACY_STAFF',
            account_status='ACTIVE',
            is_verified=True,
        )

        from .models import PharmacyMembership
        membership = PharmacyMembership.objects.create(
            user=employee,
            pharmacy=self.brand,
            role='PHARMACY_STAFF',
        )

        self.assertEqual(membership.status, 'PENDING')

        membership.approve(self.owner)
        membership.refresh_from_db()
        self.assertEqual(membership.status, 'APPROVED')
        self.assertEqual(membership.approved_by, self.owner)
