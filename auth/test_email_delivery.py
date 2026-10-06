import smtplib
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import OTPVerification, User
from .tasks import send_otp_email


@override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend')
class EmailDeliveryConfigurationTests(TestCase):
    def test_project_uses_django_smtp_backend(self):
        self.assertEqual(
            settings.EMAIL_BACKEND,
            'django.core.mail.backends.smtp.EmailBackend',
        )


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='noreply@cafsule.com',
)
class OTPEmailTaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='otp-user@example.com', password='StrongPass123!'
        )

    def test_delay_executes_task_when_celery_is_configured_eager(self):
        result = send_otp_email.delay(self.user.id, '123456', 'EMAIL_VERIFICATION')

        self.assertTrue(result.get())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn('123456', mail.outbox[0].body)

    @patch('auth.tasks.send_mail', side_effect=smtplib.SMTPAuthenticationError(535, b'auth failed'))
    def test_smtp_authentication_failure_is_reported_as_failed_task(self, mock_send_mail):
        result = send_otp_email.apply(args=(self.user.id, '123456', 'EMAIL_VERIFICATION'))

        self.assertFalse(result.get())
        mock_send_mail.assert_called_once()


@override_settings(SECURE_SSL_REDIRECT=False)
class OTPRequestDispatchTests(TestCase):
    @patch('auth.views.call_task_safely')
    def test_otp_request_queues_existing_email_task(self, mock_call_task_safely):
        user = User.objects.create_user(
            email='request-otp@example.com', password='StrongPass123!'
        )
        response = APIClient().post(
            '/api/auth/otp/request/',
            {'email': user.email, 'otp_type': 'EMAIL_VERIFICATION'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        otp = OTPVerification.objects.get(user=user, otp_type='EMAIL_VERIFICATION')
        from .tasks import send_otp_email
        mock_call_task_safely.assert_called_once_with(
            send_otp_email, user.id, otp.otp_code, 'EMAIL_VERIFICATION'
        )
