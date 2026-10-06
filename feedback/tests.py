from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from feedback.models import Feedback
from feedback.views import FeedbackCreateView

User = get_user_model()


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    FEEDBACK_RECIPIENT_EMAIL='codemaniac13@gmail.com',
)
class FeedbackSubmissionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='feedback-user@example.com',
            password='test-password',
            role='PHARMACY_OWNER',
            is_active=True,
            is_approved=True,
            account_status='ACTIVE',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.payload = {
            'feedback_type': 'BUG_REPORT',
            'subject': 'Stock count mismatch',
            'message': 'The stock count changed after refreshing the inventory page.',
            'rating': 2,
        }

    def test_feedback_is_saved_and_emailed_to_configured_recipient(self):
        response = self.client.post('/api/feedback/', self.payload, format='json')

        self.assertEqual(response.status_code, 201)
        feedback = Feedback.objects.get()
        self.assertEqual(feedback.user, self.user)
        self.assertTrue(feedback.email_sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['codemaniac13@gmail.com'])
        self.assertIn(self.payload['message'], mail.outbox[0].body)

    def test_invalid_feedback_is_rejected(self):
        response = self.client.post(
            '/api/feedback/',
            {**self.payload, 'message': 'short'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('message', response.data)
        self.assertFalse(Feedback.objects.exists())

    def test_email_failure_does_not_report_success(self):
        request = APIRequestFactory().post('/api/feedback/', self.payload, format='json')
        force_authenticate(request, user=self.user)
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend'):
            response = FeedbackCreateView.as_view()(request)

        self.assertEqual(response.status_code, 503)
        self.assertFalse(Feedback.objects.get().email_sent)

    def test_feedback_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.post('/api/feedback/', self.payload, format='json')

        self.assertEqual(response.status_code, 401)