import io
import smtplib
import socket
import ssl
from unittest.mock import Mock, patch

from django.conf import settings
from django.core import mail
from django.core.mail import get_connection
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from main.email_utils import email_failure_category

from .models import OTPVerification, User
from .serializers import EmailDeliveryUnavailable, RegisterSerializer
from .tasks import send_otp_email


class EmailDeliveryConfigurationTests(SimpleTestCase):
    def test_project_email_backend_is_loaded(self):
        backend = get_connection()
        loaded_backend = f'{backend.__class__.__module__}.{backend.__class__.__name__}'
        self.assertEqual(loaded_backend, settings.EMAIL_BACKEND)

    def test_smtp_timeout_is_bounded(self):
        self.assertGreater(settings.EMAIL_TIMEOUT, 0)

    def test_smtp_failure_categories_are_actionable_and_safe(self):
        cases = (
            (socket.gaierror('private hostname detail'), 'SMTP hostname lookup failed'),
            (TimeoutError('private timeout detail'), 'SMTP connection timed out'),
            (
                smtplib.SMTPAuthenticationError(535, b'private credential detail'),
                'SMTP authentication failed',
            ),
            (ssl.SSLError('private TLS detail'), 'SMTP TLS negotiation failed'),
            (
                smtplib.SMTPSenderRefused(550, b'private rejection detail', 'sender@example.com'),
                'SMTP sender address was rejected',
            ),
        )

        for error, expected_category in cases:
            with self.subTest(error_type=type(error).__name__):
                self.assertEqual(email_failure_category(error), expected_category)
                self.assertNotIn(str(error), expected_category)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
    EMAIL_HOST='smtp.gmail.com',
    EMAIL_PORT=587,
    EMAIL_USE_TLS=True,
    EMAIL_USE_SSL=False,
    EMAIL_TIMEOUT=11,
    EMAIL_HOST_USER='sender@example.com',
    EMAIL_HOST_PASSWORD='private-test-app-password',
    DEFAULT_FROM_EMAIL='sender@example.com',
)
class EmailDiagnosticCommandTests(SimpleTestCase):
    @patch('auth.management.commands.email_diagnostic.get_connection')
    def test_connects_and_authenticates_without_sending_a_message(self, get_connection_mock):
        connection = Mock()
        get_connection_mock.return_value = connection
        stdout = io.StringIO()

        call_command('email_diagnostic', stdout=stdout)

        get_connection_mock.assert_called_once_with(fail_silently=False, timeout=11)
        connection.open.assert_called_once()
        connection.send_messages.assert_not_called()
        self.assertIn('django.core.mail.backends.smtp.EmailBackend', stdout.getvalue())
        self.assertIn('SMTP host: smtp.gmail.com', stdout.getvalue())
        self.assertIn('SMTP port: 587', stdout.getvalue())
        self.assertIn('TLS enabled: True', stdout.getvalue())
        self.assertIn('SSL enabled: False', stdout.getvalue())

    @patch('auth.management.commands.email_diagnostic.get_connection')
    def test_authentication_error_is_classified_without_leaking_error_text(
        self,
        get_connection_mock,
    ):
        connection = Mock()
        connection.open.side_effect = smtplib.SMTPAuthenticationError(
            535,
            b'auth failed private-test-app-password',
        )
        get_connection_mock.return_value = connection
        stdout = io.StringIO()
        stderr = io.StringIO()

        with self.assertRaises(CommandError):
            call_command('email_diagnostic', stdout=stdout, stderr=stderr)

        self.assertIn('SMTP authentication failed', stderr.getvalue())
        self.assertNotIn('private-test-app-password', stdout.getvalue() + stderr.getvalue())

    @patch('auth.management.commands.email_diagnostic.get_connection')
    def test_test_email_is_sent_only_when_recipient_is_explicit(self, get_connection_mock):
        connection = Mock()
        connection.send_messages.return_value = 1
        get_connection_mock.return_value = connection
        stdout = io.StringIO()

        call_command(
            'email_diagnostic',
            '--recipient',
            'controlled@example.com',
            stdout=stdout,
        )

        connection.send_messages.assert_called_once()
        self.assertIn('does not confirm inbox delivery', stdout.getvalue())

    @override_settings(EMAIL_USE_SSL=True)
    @patch('auth.management.commands.email_diagnostic.get_connection')
    def test_refuses_mutually_enabled_tls_and_ssl(self, get_connection_mock):
        with self.assertRaises(CommandError):
            call_command('email_diagnostic', stdout=io.StringIO())

        get_connection_mock.assert_not_called()


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

    def test_otp_email_task_sends_through_configured_backend(self):
        result = send_otp_email.run(self.user.id, '123456', 'EMAIL_VERIFICATION')

        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn('123456', mail.outbox[0].body)

    @patch('auth.tasks.send_mail', side_effect=smtplib.SMTPAuthenticationError(535, b'auth failed'))
    def test_smtp_authentication_failure_is_reported_as_failed_task(self, mock_send_mail):
        result = send_otp_email.run(self.user.id, '123456', 'EMAIL_VERIFICATION')

        self.assertFalse(result)
        mock_send_mail.assert_called_once()

    @patch('auth.tasks.send_mail', side_effect=smtplib.SMTPAuthenticationError(535, b'auth failed'))
    def test_registration_does_not_succeed_when_verification_email_fails(self, mock_send_mail):
        serializer = RegisterSerializer(data={
            'email': 'new-registration@example.com',
            'first_name': 'New',
            'last_name': 'User',
            'phone_number': '+2348012345678',
            'password': 'StrongPass123!',
            'password_confirm': 'StrongPass123!',
            'role': 'PHARMACY_OWNER',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)

        with self.assertRaises(EmailDeliveryUnavailable) as raised:
            serializer.save()

        self.assertEqual(raised.exception.status_code, 503)
        self.assertFalse(User.objects.filter(email='new-registration@example.com').exists())
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
