from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import EmailVerificationToken, User
from .tokens import generate_otp


class EmailVerificationFlowTests(TestCase):
    def test_otp_verification_returns_authenticated_session_for_employee_roles(self):
        for role in ('PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF'):
            with self.subTest(role=role):
                user = User.objects.create_user(
                    email=f'{role.lower()}@example.com',
                    password='StrongPass123!',
                    first_name='Pharmacy',
                    last_name='Employee',
                    role=role,
                )
                user.account_status = 'UNVERIFIED'
                user.is_verified = False
                user.save(update_fields=['account_status', 'is_verified'])
                otp = generate_otp(user, 'EMAIL_VERIFICATION')

                response = APIClient().post(
                    '/api/auth/otp/verify/',
                    {
                        'email': user.email,
                        'otp_code': otp.otp_code,
                        'otp_type': 'EMAIL_VERIFICATION',
                    },
                    format='json',
                )

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.data['verified'])
                self.assertTrue(response.data['access'])
                self.assertTrue(response.data['refresh'])
                self.assertEqual(response.data['user']['role'], role)

    def test_email_link_verification_returns_authenticated_user_session(self):
        user = User.objects.create_user(
            email='staff@example.com',
            password='StrongPass123!',
            first_name='Staff',
            last_name='Member',
            role='PHARMACY_STAFF',
        )
        user.account_status = 'UNVERIFIED'
        user.is_verified = False
        user.save(update_fields=['account_status', 'is_verified'])
        verification_token = EmailVerificationToken.objects.create(
            user=user,
            token='email-link-token',
            expires_at=timezone.now() + timedelta(hours=1),
        )

        response = APIClient().post(
            '/api/auth/verify-email/',
            {'token': verification_token.token},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['verified'])
        self.assertTrue(response.data['access'])
        self.assertTrue(response.data['refresh'])
        self.assertEqual(response.data['user']['role'], 'PHARMACY_STAFF')
        user.refresh_from_db()
        self.assertTrue(user.is_verified)
        self.assertEqual(user.account_status, 'ACTIVE')
