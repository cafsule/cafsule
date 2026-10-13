import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from main.email_utils import SMTP_DELIVERY_EXCEPTIONS, email_failure_category

from .models import User

logger = logging.getLogger(__name__)


def _frontend_url(path):
    """Return absolute frontend URL while handling missing settings gracefully."""
    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').strip().rstrip('/')
    return f"{frontend_url}{path}" if frontend_url else path


def _send_email(subject, message, recipient, purpose, user_id):
    if settings.EMAIL_BACKEND.endswith('.console.EmailBackend'):
        logger.warning(
            '%s email not delivered for user_id=%s: console email backend is active',
            purpose,
            user_id,
        )
        return False

    try:
        sent = send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
    except SMTP_DELIVERY_EXCEPTIONS as exc:
        logger.warning(
            '%s email delivery failed for user_id=%s: %s',
            purpose,
            user_id,
            email_failure_category(exc),
        )
        return False

    if sent != 1:
        logger.warning('%s email was not accepted for user_id=%s', purpose, user_id)
        return False

    logger.info('%s email accepted by backend for user_id=%s', purpose, user_id)
    return True


@shared_task
def send_verification_email(user_id, token):
    """Send a real email verification email."""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning('Verification email skipped for missing user_id=%s', user_id)
        return False

    verification_url = _frontend_url(f"/verify-email?token={token}")
    message = f"""
    Hello {user.get_full_name() or user.email},

    Please click the link below to verify your email address:
    {verification_url}

    This link will expire in {settings.EMAIL_VERIFICATION_TOKEN_EXPIRY_HOURS} hours.

    If you didn't request this, please ignore this email.
    """
    return _send_email(
        'Verify your email address',
        message,
        user.email,
        'Verification',
        user_id,
    )


@shared_task
def send_password_reset_email(user_id, token):
    """Send a real password reset email."""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning('Password reset email skipped for missing user_id=%s', user_id)
        return False

    reset_url = _frontend_url(f"/reset-password?token={token}")
    message = f"""
    Hello {user.get_full_name() or user.email},

    You requested a password reset. Click the link below to reset your password:
    {reset_url}

    This link will expire in {settings.PASSWORD_RESET_TOKEN_EXPIRY_HOURS} hours.

    If you didn't request this, please ignore this email.
    """
    return _send_email(
        'Password Reset Request',
        message,
        user.email,
        'Password reset',
        user_id,
    )

@shared_task
def cleanup_expired_tokens():
    """Cleanup expired tokens"""
    from .models import EmailVerificationToken, PasswordResetToken
    from django.utils import timezone
    
    # Deactivate expired verification tokens
    EmailVerificationToken.objects.filter(
        expires_at__lt=timezone.now(),
        is_active=True
    ).update(is_active=False)
    
    # Deactivate expired password reset tokens
    PasswordResetToken.objects.filter(
        expires_at__lt=timezone.now(),
        is_active=True
    ).update(is_active=False)

@shared_task
def send_otp_email(user_id, otp_code, otp_type):
    """Send OTP via email"""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning('OTP email skipped for missing user_id=%s', user_id)
        return False

    purpose = otp_type.replace('_', ' ').title()
    message = f"""
    Hello {user.get_full_name() or user.email},

    Your OTP code for {otp_type.replace('_', ' ').lower()} is:

    {otp_code}

    This code will expire in 10 minutes.

    If you didn't request this, please ignore this email.
    """
    return _send_email(
        f'Your {purpose} OTP Code',
        message,
        user.email,
        'OTP',
        user_id,
    )

@shared_task
def send_otp_sms(user_id, otp_code):
    """Send OTP via SMS (using your SMS provider)"""
    try:
        user = User.objects.get(id=user_id)
        
        # This is a placeholder - implement with your SMS provider
        # Example with Twilio:
        # from twilio.rest import Client
        # client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        # client.messages.create(
        #     body=f"Your OTP code is: {otp_code}",
        #     from_=settings.TWILIO_PHONE_NUMBER,
        #     to=user.phone_number
        # )
        
        logger.info(f"OTP SMS sent to {user.phone_number}: {otp_code}")
        return True
    except Exception as e:
        logger.error(f"OTP SMS sending failed: {str(e)}")
        return False


@shared_task
def send_approval_notification(user_id, action):
    """Send approval/rejection notification email"""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning('Approval email skipped for missing user_id=%s', user_id)
        return False

    if action == 'approve':
        subject = "Your account has been approved"
        message = f"""
        Hello {user.get_full_name() or user.email},

        Your account has been approved by the pharmacy owner.
        You can now log in and access the system.

        Thank you,
        Pharmacy IMS Team
        """
    else:
        subject = "Your account has been rejected"
        message = f"""
        Hello {user.get_full_name() or user.email},

        Your account has been rejected by the pharmacy owner.
        Please contact the pharmacy owner for more information.

        Thank you,
        Pharmacy IMS Team
        """

    return _send_email(subject, message, user.email, 'Approval', user_id)


@shared_task
def send_approval_request_notification(owner_id, new_user_id):
    """Notify pharmacy owner about new user waiting for approval"""
    try:
        owner = User.objects.get(id=owner_id)
        new_user = User.objects.get(id=new_user_id)
    except User.DoesNotExist:
        logger.warning('Approval request email skipped because a user no longer exists')
        return False

    message = f"""
    Hello {owner.get_full_name() or owner.email},

    A new user has registered and is waiting for your approval:

    Name: {new_user.get_full_name()}
    Email: {new_user.email}
    Role: {new_user.get_role_display()}

    Please log in to approve or reject this user.

    Thank you,
    Pharmacy IMS Team
    """
    return _send_email(
        "New user waiting for approval",
        message,
        owner.email,
        'Approval request',
        owner_id,
    )