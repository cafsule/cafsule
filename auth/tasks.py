import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from .models import User

logger = logging.getLogger(__name__)


def _frontend_url(path):
    """Return absolute frontend URL while handling missing settings gracefully."""
    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').strip().rstrip('/')
    return f"{frontend_url}{path}" if frontend_url else path


@shared_task
def send_verification_email(user_id, token):
    """Send a real email verification email."""
    try:
        user = User.objects.get(id=user_id)
        verification_url = _frontend_url(f"/verify-email?token={token}")

        subject = 'Verify your email address'
        message = f"""
        Hello {user.get_full_name() or user.email},

        Please click the link below to verify your email address:
        {verification_url}

        This link will expire in {settings.EMAIL_VERIFICATION_TOKEN_EXPIRY_HOURS} hours.

        If you didn't request this, please ignore this email.
        """

        sent = send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )

        if sent:
            logger.info('Verification email sent to %s', user.email)
            return True

        logger.warning('Verification email send_mail returned 0 for %s', user.email)
        return False
    except Exception:
        logger.exception('Verification email sending failed for user_id=%s', user_id)
        return False


@shared_task
def send_password_reset_email(user_id, token):
    """Send a real password reset email."""
    try:
        user = User.objects.get(id=user_id)
        reset_url = _frontend_url(f"/reset-password?token={token}")

        subject = 'Password Reset Request'
        message = f"""
        Hello {user.get_full_name() or user.email},

        You requested a password reset. Click the link below to reset your password:
        {reset_url}

        This link will expire in {settings.PASSWORD_RESET_TOKEN_EXPIRY_HOURS} hours.

        If you didn't request this, please ignore this email.
        """

        sent = send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )

        if sent:
            logger.info('Password reset email sent to %s', user.email)
            return True

        logger.warning('Password reset email send_mail returned 0 for %s', user.email)
        return False
    except Exception:
        logger.exception('Password reset email sending failed for user_id=%s', user_id)
        return False

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
        
        subject = f"Your {otp_type.replace('_', ' ').title()} OTP Code"
        message = f"""
        Hello {user.get_full_name() or user.email},
        
        Your OTP code for {otp_type.replace('_', ' ').lower()} is:
        
        {otp_code}
        
        This code will expire in 10 minutes.
        
        If you didn't request this, please ignore this email.
        """
        
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False
        )
        return True
    except Exception as e:
        logger.error(f"OTP email sending failed: {str(e)}")
        return False

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
        
        if action == 'approve':
            subject = "Your account has been approved"
            message = f"""
            Hello {user.get_full_name() or user.email},
            
            Your account has been approved by the pharmacy owner.
            You can now log in and access the system.
            
            Thank you,
            Pharmacy IMS Team
            """
        else:  # reject
            subject = "Your account has been rejected"
            message = f"""
            Hello {user.get_full_name() or user.email},
            
            Your account has been rejected by the pharmacy owner.
            Please contact the pharmacy owner for more information.
            
            Thank you,
            Pharmacy IMS Team
            """
        
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False
        )
        return True
    except Exception as e:
        logger.error(f"Approval notification failed: {str(e)}")
        return False

@shared_task
def send_approval_request_notification(owner_id, new_user_id):
    """Notify pharmacy owner about new user waiting for approval"""
    try:
        owner = User.objects.get(id=owner_id)
        new_user = User.objects.get(id=new_user_id)
        
        subject = "New user waiting for approval"
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
        
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [owner.email],
            fail_silently=False
        )
        return True
    except Exception as e:
        logger.error(f"Approval request notification failed: {str(e)}")
        return False