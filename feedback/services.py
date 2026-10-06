import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_feedback_notification(feedback):
    if settings.EMAIL_BACKEND.endswith('.console.EmailBackend'):
        raise ImproperlyConfigured(
            'Configure an SMTP email backend before enabling feedback email delivery.'
        )

    user = feedback.user
    user_name = user.get_full_name() if user else 'Deleted account'
    user_email = user.email if user else 'Unavailable'
    user_role = getattr(user, 'role', 'Unavailable') if user else 'Unavailable'
    subject = f'[Cafsule feedback] {feedback.subject}'.replace('\r', ' ').replace('\n', ' ')
    body = '\n'.join((
        f'Type: {feedback.get_feedback_type_display()}',
        f'Subject: {feedback.subject}',
        f'Rating: {feedback.rating if feedback.rating is not None else "Not provided"}',
        '',
        'Message:',
        feedback.message,
        '',
        f'From: {user_name} <{user_email}>',
        f'Role: {user_role}',
        f'Submitted: {feedback.created_at.isoformat()}',
        f'Feedback ID: {feedback.pk}',
    ))

    sent_count = send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[settings.FEEDBACK_RECIPIENT_EMAIL],
        fail_silently=False,
    )
    if sent_count != 1:
        raise RuntimeError('The feedback notification email was not accepted by the mail backend.')

    logger.info('Feedback notification sent for feedback id=%s', feedback.pk)