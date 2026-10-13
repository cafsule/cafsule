import smtplib
import socket
import ssl

from django.core.exceptions import ImproperlyConfigured

SMTP_DELIVERY_EXCEPTIONS = (smtplib.SMTPException, OSError, TimeoutError)

EMAIL_DELIVERY_EXCEPTIONS = (
    *SMTP_DELIVERY_EXCEPTIONS,
    ImproperlyConfigured,
    RuntimeError,
)


def email_failure_category(error):
    """Return a safe diagnostic label without exposing server responses or credentials."""
    if isinstance(error, socket.gaierror):
        return 'SMTP hostname lookup failed'
    if isinstance(error, TimeoutError):
        return 'SMTP connection timed out'
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return 'SMTP authentication failed'
    if isinstance(error, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
        return 'SMTP TLS negotiation failed'
    if isinstance(error, smtplib.SMTPSenderRefused):
        return 'SMTP sender address was rejected'
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return 'SMTP recipient address was rejected'
    if isinstance(error, (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError)):
        return 'SMTP connection failed'
    if isinstance(error, smtplib.SMTPException):
        return 'SMTP protocol operation failed'
    if isinstance(error, RuntimeError):
        return 'Email backend did not accept the message'
    return 'Email delivery failed'
