from django.core import mail
from django.test import TestCase, override_settings

from .models import User
from .tasks import send_password_reset_email, send_verification_email


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
