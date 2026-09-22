"""
Comprehensive tests for the Pharmacy Membership / Staff Onboarding workflow.

Tests cover:
1. Staff registration with pharmacy selection
2. Pharmacy owner approval workflow
3. Cross-pharmacy security boundaries
4. Dashboard access rules
5. Permission enforcement
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
import json

from pharmacy.models import PharmacyBrand, PharmacyMembership

User = get_user_model()


class StaffRegistrationWorkflowTests(TestCase):
    """Test staff registration with pharmacy selection"""

    def setUp(self):
        """Set up test data"""
        self.client = APIClient()
        
        # Create a pharmacy owner
        self.owner = User.objects.create_user(
            email='owner@pharmacy.com',
            password='testpass123!',
            first_name='John',
            last_name='Owner',
            role='PHARMACY_OWNER'
        )
        self.owner.is_verified = True
        self.owner.is_active = True
        self.owner.account_status = 'ACTIVE'
        self.owner.save()
        
        # Create a verified pharmacy
        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Test Pharmacy Legal',
            brand_name='Test Pharmacy',
            verification_status='VERIFIED'
        )
        
        unverified_owner = User.objects.create_user(
            email='unverified-owner@pharmacy.com',
            password='testpass123!',
            role='PHARMACY_OWNER',
            is_verified=True,
            is_active=True,
            account_status='ACTIVE',
        )
        # Create an unverified pharmacy
        self.unverified_pharmacy = PharmacyBrand.objects.create(
            owner=unverified_owner,
            legal_name='Unverified Pharmacy Legal',
            brand_name='Unverified Pharmacy',
            verification_status='PENDING_VERIFICATION'
        )

    def test_staff_can_register_without_pharmacy_selection(self):
        """Employees register first and join after email verification."""
        payload = {
            'email': 'pharmacist@test.com',
            'password': 'testpass123!',
            'password_confirm': 'testpass123!',
            'first_name': 'Jane',
            'last_name': 'Pharmacist',
            'role': 'PHARMACIST',
        }
        
        response = self.client.post('/api/auth/register/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify user was created
        user = User.objects.get(email='pharmacist@test.com')
        self.assertEqual(user.role, 'PHARMACIST')
        
        self.assertFalse(PharmacyMembership.objects.filter(user=user).exists())

    def test_staff_registration_ignores_legacy_pharmacy_selection(self):
        """Legacy pharmacy selection does not create a membership."""
        payload = {
            'email': 'manager@test.com',
            'password': 'testpass123!',
            'password_confirm': 'testpass123!',
            'first_name': 'Bob',
            'last_name': 'Manager',
            'role': 'PHARMACY_MANAGER',
            'pharmacy_brand': str(self.unverified_pharmacy.id)
        }
        
        response = self.client.post('/api/auth/register/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='manager@test.com')
        self.assertFalse(PharmacyMembership.objects.filter(user=user).exists())

    def test_staff_registration_without_pharmacy_succeeds(self):
        """Employees choose a pharmacy after email verification."""
        payload = {
            'email': 'staff@test.com',
            'password': 'testpass123!',
            'password_confirm': 'testpass123!',
            'first_name': 'Alice',
            'last_name': 'Staff',
            'role': 'PHARMACY_STAFF'
        }
        
        response = self.client.post('/api/auth/register/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_pharmacy_owner_cannot_provide_pharmacy_during_registration(self):
        """Test that pharmacy owner should not provide pharmacy during registration"""
        payload = {
            'email': 'owner2@test.com',
            'password': 'testpass123!',
            'password_confirm': 'testpass123!',
            'first_name': 'New',
            'last_name': 'Owner',
            'role': 'PHARMACY_OWNER',
            'pharmacy_brand': str(self.pharmacy.id)
        }
        
        response = self.client.post('/api/auth/register/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(PharmacyMembership.objects.filter(user__email='owner2@test.com').exists())

    def test_pharmacy_owner_registration_without_pharmacy(self):
        """Test that pharmacy owner can register without pharmacy selection"""
        payload = {
            'email': 'owner3@test.com',
            'password': 'testpass123!',
            'password_confirm': 'testpass123!',
            'first_name': 'New',
            'last_name': 'Owner',
            'role': 'PHARMACY_OWNER'
        }
        
        response = self.client.post('/api/auth/register/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        user = User.objects.get(email='owner3@test.com')
        self.assertEqual(user.role, 'PHARMACY_OWNER')


class PharmacyOwnerApprovalWorkflowTests(TestCase):
    """Test pharmacy owner approval of pending staff"""

    def setUp(self):
        """Set up test data"""
        self.client = APIClient()
        
        # Create two pharmacy owners
        self.owner1 = User.objects.create_user(
            email='owner1@pharmacy.com',
            password='testpass123!',
            first_name='Owner',
            last_name='One',
            role='PHARMACY_OWNER'
        )
        self.owner1.is_verified = True
        self.owner1.is_active = True
        self.owner1.account_status = 'ACTIVE'
        self.owner1.save()
        
        self.owner2 = User.objects.create_user(
            email='owner2@pharmacy.com',
            password='testpass123!',
            first_name='Owner',
            last_name='Two',
            role='PHARMACY_OWNER'
        )
        self.owner2.is_verified = True
        self.owner2.is_active = True
        self.owner2.account_status = 'ACTIVE'
        self.owner2.save()
        
        # Create pharmacies for each owner
        self.pharmacy1 = PharmacyBrand.objects.create(
            owner=self.owner1,
            legal_name='Pharmacy One',
            brand_name='Pharmacy One',
            verification_status='VERIFIED'
        )
        
        self.pharmacy2 = PharmacyBrand.objects.create(
            owner=self.owner2,
            legal_name='Pharmacy Two',
            brand_name='Pharmacy Two',
            verification_status='VERIFIED'
        )
        
        # Create pending staff for pharmacy1
        self.staff = User.objects.create_user(
            email='staff@test.com',
            password='testpass123!',
            first_name='Staff',
            last_name='Member',
            role='PHARMACY_STAFF'
        )
        self.staff.is_verified = True
        self.staff.is_active = True
        self.staff.save()
        
        self.membership = PharmacyMembership.objects.create(
            user=self.staff,
            pharmacy=self.pharmacy1,
            role='PHARMACY_STAFF',
            status='PENDING'
        )

    def test_correct_owner_can_see_pending_staff(self):
        """Test that the correct pharmacy owner can see pending staff"""
        self.client.force_authenticate(user=self.owner1)
        
        response = self.client.get(f'/api/pharmacy/brands/{self.pharmacy1.id}/membership-requests/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['user']['email'], 'staff@test.com')

    def test_wrong_owner_cannot_see_other_pharmacy_staff(self):
        """Test that owner of pharmacy B cannot see staff of pharmacy A"""
        self.client.force_authenticate(user=self.owner2)
        
        response = self.client.get(f'/api/pharmacy/brands/{self.pharmacy1.id}/membership-requests/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_approve_their_own_staff(self):
        """Test that pharmacy owner can approve their own staff"""
        self.client.force_authenticate(user=self.owner1)
        
        response = self.client.post(f'/api/pharmacy/memberships/{self.membership.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify membership status changed
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, 'APPROVED')
        self.assertEqual(self.membership.approved_by_id, self.owner1.id)

    def test_wrong_owner_cannot_approve_other_pharmacy_staff(self):
        """Test that owner B cannot approve staff of pharmacy A"""
        self.client.force_authenticate(user=self.owner2)
        
        response = self.client.post(f'/api/pharmacy/memberships/{self.membership.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Verify membership status did not change
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, 'PENDING')

    def test_staff_cannot_approve_other_staff(self):
        """Test that regular staff cannot approve other staff"""
        self.client.force_authenticate(user=self.staff)
        
        response = self.client.post(f'/api/pharmacy/memberships/{self.membership.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_reject_staff_with_reason(self):
        """Test that pharmacy owner can reject staff with a reason"""
        self.client.force_authenticate(user=self.owner1)
        
        payload = {'reason': 'Applicant is not currently employed by this pharmacy'}
        response = self.client.post(f'/api/pharmacy/memberships/{self.membership.id}/reject/', payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify membership was rejected with reason
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, 'REJECTED')
        self.assertEqual(self.membership.rejection_reason, 'Applicant is not currently employed by this pharmacy')
        self.assertEqual(self.membership.approved_by_id, self.owner1.id)

    def test_rejection_without_reason_fails(self):
        """Test that rejection without reason fails"""
        self.client.force_authenticate(user=self.owner1)
        
        response = self.client.post(f'/api/pharmacy/memberships/{self.membership.id}/reject/', {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        # Verify membership was not rejected
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, 'PENDING')

    def test_wrong_owner_cannot_reject_other_pharmacy_staff(self):
        """Test that owner B cannot reject staff of pharmacy A"""
        self.client.force_authenticate(user=self.owner2)
        
        payload = {'reason': 'Some reason'}
        response = self.client.post(f'/api/pharmacy/memberships/{self.membership.id}/reject/', payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Verify membership was not rejected
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, 'PENDING')


class DashboardAccessControlTests(TestCase):
    """Test that dashboard access is restricted based on membership status"""

    def setUp(self):
        """Set up test data"""
        self.client = APIClient()
        
        # Create pharmacy owner
        self.owner = User.objects.create_user(
            email='owner@pharmacy.com',
            password='testpass123!',
            first_name='Owner',
            last_name='One',
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
        
        # Create approved staff
        self.approved_staff = User.objects.create_user(
            email='approved@test.com',
            password='testpass123!',
            first_name='Approved',
            last_name='Staff',
            role='PHARMACIST'
        )
        self.approved_staff.is_verified = True
        self.approved_staff.is_active = True
        self.approved_staff.save()
        
        self.approved_membership = PharmacyMembership.objects.create(
            user=self.approved_staff,
            pharmacy=self.pharmacy,
            role='PHARMACIST',
            status='APPROVED',
            approved_by=self.owner
        )
        
        # Create pending staff
        self.pending_staff = User.objects.create_user(
            email='pending@test.com',
            password='testpass123!',
            first_name='Pending',
            last_name='Staff',
            role='PHARMACIST'
        )
        self.pending_staff.is_verified = True
        self.pending_staff.is_active = True
        self.pending_staff.save()
        
        self.pending_membership = PharmacyMembership.objects.create(
            user=self.pending_staff,
            pharmacy=self.pharmacy,
            role='PHARMACIST',
            status='PENDING'
        )
        
        # Create rejected staff
        self.rejected_staff = User.objects.create_user(
            email='rejected@test.com',
            password='testpass123!',
            first_name='Rejected',
            last_name='Staff',
            role='PHARMACIST'
        )
        self.rejected_staff.is_verified = True
        self.rejected_staff.is_active = True
        self.rejected_staff.save()
        
        self.rejected_membership = PharmacyMembership.objects.create(
            user=self.rejected_staff,
            pharmacy=self.pharmacy,
            role='PHARMACIST',
            status='REJECTED',
            approved_by=self.owner,
            rejection_reason='Not eligible'
        )

    def test_approved_staff_can_see_their_membership(self):
        """Test that approved staff can see their own membership"""
        self.client.force_authenticate(user=self.approved_staff)
        
        response = self.client.get('/api/pharmacy/my-memberships/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['status'], 'APPROVED')

    def test_pending_staff_can_see_their_membership(self):
        """Test that pending staff can see their own membership"""
        self.client.force_authenticate(user=self.pending_staff)
        
        response = self.client.get('/api/pharmacy/my-memberships/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['status'], 'PENDING')

    def test_rejected_staff_can_see_their_membership(self):
        """Test that rejected staff can see their own membership with rejection reason"""
        self.client.force_authenticate(user=self.rejected_staff)
        
        response = self.client.get('/api/pharmacy/my-memberships/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['status'], 'REJECTED')
        self.assertEqual(response.data[0]['rejection_reason'], 'Not eligible')


class CrossPharmacySecurityTests(TestCase):
    """Test cross-pharmacy security boundaries"""

    def setUp(self):
        """Set up test data"""
        self.client = APIClient()
        
        # Create two pharmacy owners
        self.owner_a = User.objects.create_user(
            email='owner_a@pharmacy.com',
            password='testpass123!',
            first_name='Owner',
            last_name='A',
            role='PHARMACY_OWNER'
        )
        self.owner_a.is_verified = True
        self.owner_a.is_active = True
        self.owner_a.account_status = 'ACTIVE'
        self.owner_a.save()
        
        self.owner_b = User.objects.create_user(
            email='owner_b@pharmacy.com',
            password='testpass123!',
            first_name='Owner',
            last_name='B',
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
        
        # Create staff for pharmacy_a
        self.staff_a = User.objects.create_user(
            email='staff_a@test.com',
            password='testpass123!',
            first_name='Staff',
            last_name='A',
            role='PHARMACIST'
        )
        self.staff_a.is_verified = True
        self.staff_a.is_active = True
        self.staff_a.save()
        
        self.membership_a = PharmacyMembership.objects.create(
            user=self.staff_a,
            pharmacy=self.pharmacy_a,
            role='PHARMACIST',
            status='PENDING'
        )

    def test_owner_a_cannot_see_pharmacy_b_staff(self):
        """Test that Owner A cannot see staff of Pharmacy B"""
        self.client.force_authenticate(user=self.owner_a)
        
        # Try to access pharmacy B's membership requests
        response = self.client.get(f'/api/pharmacy/brands/{self.pharmacy_b.id}/membership-requests/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_a_cannot_modify_pharmacy_b_membership(self):
        """Test that Owner A cannot modify Pharmacy B's membership"""
        # Create a membership for pharmacy B
        staff_b = User.objects.create_user(
            email='staff_b@test.com',
            password='testpass123!',
            first_name='Staff',
            last_name='B',
            role='PHARMACIST'
        )
        staff_b.is_verified = True
        staff_b.is_active = True
        staff_b.save()
        
        membership_b = PharmacyMembership.objects.create(
            user=staff_b,
            pharmacy=self.pharmacy_b,
            role='PHARMACIST',
            status='PENDING'
        )
        
        self.client.force_authenticate(user=self.owner_a)
        
        # Try to approve pharmacy B's staff
        response = self.client.post(f'/api/pharmacy/memberships/{membership_b.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Verify membership was not approved
        membership_b.refresh_from_db()
        self.assertEqual(membership_b.status, 'PENDING')

    def test_owner_a_can_only_see_own_pharmacy(self):
        """Test that Owner A can only see their own pharmacy's staff requests"""
        self.client.force_authenticate(user=self.owner_a)
        
        response = self.client.get(f'/api/pharmacy/brands/{self.pharmacy_a.id}/membership-requests/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['user']['email'], 'staff_a@test.com')

    def test_staff_a_cannot_access_pharmacy_b_approval_actions(self):
        """Test that staff of pharmacy A cannot access approval actions on pharmacy B"""
        # Create a membership for pharmacy B
        staff_b = User.objects.create_user(
            email='staff_b@test.com',
            password='testpass123!',
            first_name='Staff',
            last_name='B',
            role='PHARMACIST'
        )
        staff_b.is_verified = True
        staff_b.is_active = True
        staff_b.save()
        
        membership_b = PharmacyMembership.objects.create(
            user=staff_b,
            pharmacy=self.pharmacy_b,
            role='PHARMACIST',
            status='PENDING'
        )
        
        self.client.force_authenticate(user=self.staff_a)
        
        # Try to approve pharmacy B's staff
        response = self.client.post(f'/api/pharmacy/memberships/{membership_b.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class PlatformAdminAccessTests(TestCase):
    """Test that platform admins have appropriate access"""

    def setUp(self):
        """Set up test data"""
        self.client = APIClient()
        
        # Create platform admin
        self.admin = User.objects.create_user(
            email='admin@platform.com',
            password='testpass123!',
            first_name='Platform',
            last_name='Admin',
            role='PLATFORM_ADMIN'
        )
        self.admin.is_verified = True
        self.admin.is_active = True
        self.admin.account_status = 'ACTIVE'
        self.admin.save()
        
        # Create pharmacy owner
        self.owner = User.objects.create_user(
            email='owner@pharmacy.com',
            password='testpass123!',
            first_name='Owner',
            last_name='One',
            role='PHARMACY_OWNER'
        )
        self.owner.is_verified = True
        self.owner.is_active = True
        self.owner.account_status = 'ACTIVE'
        self.owner.save()
        
        # Create pharmacy
        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Test Pharmacy',
            brand_name='Test Pharmacy',
            verification_status='VERIFIED'
        )
        
        # Create pending staff
        self.staff = User.objects.create_user(
            email='staff@test.com',
            password='testpass123!',
            first_name='Staff',
            last_name='Member',
            role='PHARMACIST'
        )
        self.staff.is_verified = True
        self.staff.is_active = True
        self.staff.save()
        
        self.membership = PharmacyMembership.objects.create(
            user=self.staff,
            pharmacy=self.pharmacy,
            role='PHARMACIST',
            status='PENDING'
        )

    def test_platform_admin_can_approve_any_staff(self):
        """Test that platform admin can approve staff from any pharmacy"""
        self.client.force_authenticate(user=self.admin)
        
        response = self.client.post(f'/api/pharmacy/memberships/{self.membership.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, 'APPROVED')

    def test_platform_admin_can_reject_any_staff(self):
        """Test that platform admin can reject staff from any pharmacy"""
        self.client.force_authenticate(user=self.admin)
        
        payload = {'reason': 'Platform policy violation'}
        response = self.client.post(f'/api/pharmacy/memberships/{self.membership.id}/reject/', payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, 'REJECTED')
