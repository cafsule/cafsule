from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from .models import User, UserActivityLog
from .serializers import SocialAuthSerializer
from pharmacy.models import PharmacyBrand, PharmacyVerificationHistory
from .tasks import send_password_reset_email, send_verification_email


@override_settings(SOCIAL_AUTH_GOOGLE_OAUTH2_KEY='cafsule-test-client-id')
class SocialAuthTokenValidationTests(SimpleTestCase):
    def test_unverified_client_identity_fields_are_not_accepted(self):
        serializer = SocialAuthSerializer(data={
            'provider': 'GOOGLE',
            'provider_user_id': 'attacker-selected-id',
            'email': 'victim@example.com',
        })

        self.assertFalse(serializer.is_valid())
        self.assertIn('id_token', serializer.errors)

    def test_identity_fields_are_taken_from_verified_google_claims(self):
        from unittest.mock import patch

        claims = {
            'sub': 'verified-google-id',
            'email': 'verified@example.com',
            'email_verified': True,
            'given_name': 'Verified',
            'family_name': 'Person',
        }
        with patch('google.oauth2.id_token.verify_oauth2_token', return_value=claims) as verify:
            serializer = SocialAuthSerializer(data={
                'provider': 'GOOGLE',
                'id_token': 'signed-google-id-token',
                'provider_user_id': 'attacker-selected-id',
                'email': 'attacker@example.com',
                'first_name': 'Attacker',
            })

            self.assertTrue(serializer.is_valid(), serializer.errors)
            self.assertEqual(serializer.validated_data['provider_user_id'], 'verified-google-id')
            self.assertEqual(serializer.validated_data['email'], 'verified@example.com')
            self.assertEqual(serializer.validated_data['first_name'], 'Verified')
            verify.assert_called_once()


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    FRONTEND_URL='http://localhost:3000',
)
class EmailTasksTests(TestCase):
    def test_send_verification_email_sends_verification_link(self):
        user = User.objects.create_user(
            email='newuser@example.com',
            password='StrongPass123!',
            first_name='Jane',
            last_name='Doe',
        )

        result = send_verification_email(user.id, 'test-token-123')

        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Verify your email address', mail.outbox[0].subject)
        self.assertIn('http://localhost:3000/verify-email?token=test-token-123', mail.outbox[0].body)

    def test_send_password_reset_email_sends_reset_link(self):
        user = User.objects.create_user(
            email='resetuser@example.com',
            password='StrongPass123!',
            first_name='Reset',
            last_name='User',
        )

        result = send_password_reset_email(user.id, 'reset-token-456')

        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Password Reset Request', mail.outbox[0].subject)
        self.assertIn('http://localhost:3000/reset-password?token=reset-token-456', mail.outbox[0].body)


class PlatformActivityEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_platform_activity_requires_platform_admin(self):
        owner = User.objects.create_user(
            email='owner@example.com',
            password='StrongPass123!',
            first_name='Owner',
            last_name='User',
            role='PHARMACY_OWNER',
            is_active=True,
            is_verified=True,
            account_status='ACTIVE',
        )
        self.client.force_authenticate(owner)
        response = self.client.get('/api/auth/platform-activity/')
        self.assertEqual(response.status_code, 403)

    def test_platform_activity_returns_real_backend_events(self):
        admin = User.objects.create_user(
            email='admin@example.com',
            password='StrongPass123!',
            first_name='Platform',
            last_name='Admin',
            role='SUPER_ADMIN',
            is_active=True,
            is_verified=True,
            account_status='ACTIVE',
        )
        owner = User.objects.create_user(
            email='pharmacy-owner@example.com',
            password='StrongPass123!',
            first_name='Pharmacy',
            last_name='Owner',
            role='PHARMACY_OWNER',
            is_active=True,
            is_verified=True,
            account_status='ACTIVE',
        )
        brand = PharmacyBrand.objects.create(
            owner=owner,
            legal_name='Acme Pharmacy',
            brand_name='Acme Pharmacy',
            city='Lagos',
            state='Lagos',
            country='Nigeria',
            verification_status='PENDING_VERIFICATION',
        )
        UserActivityLog.objects.create(
            user=owner,
            action='REGISTRATION',
            details={'email': owner.email, 'role': owner.role},
        )
        PharmacyVerificationHistory.objects.create(
            pharmacy_brand=brand,
            previous_status='DRAFT',
            new_status='PENDING_VERIFICATION',
            action='SUBMITTED',
            performed_by=admin,
        )

        self.client.force_authenticate(admin)
        response = self.client.get('/api/auth/platform-activity/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload), 2)
        actions = {item['action'] for item in payload}
        self.assertIn('Registration', actions)
        self.assertIn('Submitted', actions)
