from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from .models import Expense
from .serializers import ExpenseSerializer
from .views import ExpenseViewSet, can_approve_expense
from pharmacy.models import PharmacyBrand, PharmacyMembership

User = get_user_model()


class ExpenseWorkflowTest(SimpleTestCase):
    def test_new_expenses_require_approval(self):
        self.assertEqual(Expense().status, 'PENDING')

    def test_amount_must_be_positive(self):
        serializer = ExpenseSerializer(data={
            'category': 'OTHER',
            'amount': Decimal('0.00'),
            'expense_date': '2026-01-01',
            'description': 'Invalid expense',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('amount', serializer.errors)

    def test_owner_can_approve_expense(self):
        user = SimpleNamespace(role='PHARMACY_OWNER', is_authenticated=True)
        self.assertTrue(can_approve_expense(user))

    def test_manager_cannot_approve_expense(self):
        user = SimpleNamespace(role='PHARMACY_MANAGER', is_authenticated=True)
        self.assertFalse(can_approve_expense(user))


class ExpenseMembershipWorkflowTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='expense-owner@example.com',
            password='password',
            role='PHARMACY_OWNER',
            is_active=True,
            is_approved=True,
            account_status='ACTIVE',
        )
        self.pharmacy = PharmacyBrand.objects.create(
            owner=self.owner,
            legal_name='Expense Pharmacy',
            brand_name='Expense Pharmacy',
            verification_status='VERIFIED',
        )
        self.factory = APIRequestFactory()

    def create_expense(self, user, pharmacy_id=None):
        payload = {
            'category': 'UTILITIES',
            'amount': '25000.00',
            'expense_date': '2026-09-17',
            'description': 'Generator fuel',
            'payment_method': 'CASH',
        }
        if pharmacy_id:
            payload['pharmacy'] = str(pharmacy_id)
        request = self.factory.post('/api/expenses/', payload, format='json')
        force_authenticate(request, user=user)
        return ExpenseViewSet.as_view({'post': 'create'})(request)

    def test_all_pharmacy_roles_create_for_approved_membership(self):
        for role in ('PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF'):
            user = User.objects.create_user(
                email=f'{role.lower()}@example.com',
                password='password',
                role=role,
                is_active=True,
                is_approved=True,
                account_status='ACTIVE',
            )
            PharmacyMembership.objects.create(
                pharmacy=self.pharmacy,
                user=user,
                role=role,
                status='APPROVED',
                approved_by=self.owner,
            )

            response = self.create_expense(user)

            self.assertEqual(response.status_code, 201)
            self.assertEqual(str(response.data['pharmacy']), str(self.pharmacy.id))
            self.assertEqual(response.data['status'], 'PENDING')
            self.assertEqual(str(response.data['created_by']), str(user.id))

        response = self.create_expense(self.owner)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(str(response.data['pharmacy']), str(self.pharmacy.id))

    def test_employee_cannot_create_for_another_pharmacy(self):
        other_owner = User.objects.create_user(
            email='other-owner@example.com',
            password='password',
            role='PHARMACY_OWNER',
            is_active=True,
            is_approved=True,
            account_status='ACTIVE',
        )
        other_pharmacy = PharmacyBrand.objects.create(
            owner=other_owner,
            legal_name='Other Pharmacy',
            brand_name='Other Pharmacy',
            verification_status='VERIFIED',
        )
        employee = User.objects.create_user(
            email='staff@example.com',
            password='password',
            role='PHARMACY_STAFF',
            is_active=True,
            is_approved=True,
            account_status='ACTIVE',
        )
        PharmacyMembership.objects.create(
            pharmacy=self.pharmacy,
            user=employee,
            role='PHARMACY_STAFF',
            status='APPROVED',
            approved_by=self.owner,
        )

        response = self.create_expense(employee, other_pharmacy.id)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Expense.objects.filter(created_by=employee).exists())

    def test_non_owner_cannot_approve_expense(self):
        employee = User.objects.create_user(
            email='manager@example.com',
            password='password',
            role='PHARMACY_MANAGER',
            is_active=True,
            is_approved=True,
            account_status='ACTIVE',
        )
        PharmacyMembership.objects.create(
            pharmacy=self.pharmacy,
            user=employee,
            role='PHARMACY_MANAGER',
            status='APPROVED',
            approved_by=self.owner,
        )
        expense = Expense.objects.create(
            pharmacy=self.pharmacy,
            category='OTHER',
            amount=Decimal('100.00'),
            description='Pending expense',
            created_by=employee,
        )
        request = self.factory.post(f'/api/expenses/{expense.id}/approve/', {}, format='json')
        force_authenticate(request, user=employee)

        response = ExpenseViewSet.as_view({'post': 'approve'})(request, pk=expense.id)

        self.assertEqual(response.status_code, 403)
        expense.refresh_from_db()
        self.assertEqual(expense.status, 'PENDING')
