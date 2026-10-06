from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import EmailVerificationToken, OTPVerification, User
from .tokens import generate_otp


@override_settings(SECURE_SSL_REDIRECT=False)
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

    @patch('auth.tasks.send_otp_email')
    @patch('auth.tasks.send_verification_email')
    def test_registration_uses_otp_flow_instead_of_legacy_link_email(
        self,
        mock_send_verification_email,
        mock_send_otp_email,
    ):

        response = APIClient().post(
            '/api/auth/register/',
            {
                'email': 'newuser@example.com',
                'first_name': 'New',
                'last_name': 'User',
                'phone_number': '+2348123456789',
                'password': 'StrongPass123!',
                'password_confirm': 'StrongPass123!',
                'role': 'PHARMACY_STAFF',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email='newuser@example.com')
        otp = OTPVerification.objects.get(user=user, otp_type='EMAIL_VERIFICATION')
        mock_send_otp_email.assert_called_once_with(
            user.id, otp.otp_code, 'EMAIL_VERIFICATION'
        )
        mock_send_verification_email.assert_not_called()
        self.assertFalse(EmailVerificationToken.objects.filter(user=user).exists())
        self.assertTrue(OTPVerification.objects.filter(user=user, otp_type='EMAIL_VERIFICATION').exists())

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
