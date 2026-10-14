import errno
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


def email_failure_exception_types(error):
    """Return exception class names only, including wrapped low-level causes."""
    exception_types = []
    seen = set()
    while isinstance(error, BaseException) and id(error) not in seen:
        seen.add(id(error))
        exception_types.append(type(error).__name__)
        error = error.__cause__ or error.__context__
    return ' -> '.join(exception_types)


def _direct_email_failure_category(error):
    if isinstance(error, socket.gaierror):
        return 'SMTP hostname lookup failed'
    if isinstance(error, TimeoutError):
        return 'SMTP connection timed out'
    if isinstance(error, ConnectionRefusedError) or (
        isinstance(error, OSError) and error.errno == errno.ECONNREFUSED
    ):
        return 'SMTP connection was refused'
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


def email_failure_category(error):
    """Return a safe diagnostic label without exposing server responses or credentials."""
    seen = set()
    fallback_category = None
    while isinstance(error, BaseException) and id(error) not in seen:
        seen.add(id(error))
        category = _direct_email_failure_category(error)
        if category not in (
            'Email delivery failed',
            'SMTP connection failed',
            'SMTP protocol operation failed',
        ):
            return category
        if fallback_category is None and category != 'Email delivery failed':
            fallback_category = category
        error = error.__cause__ or error.__context__
    return fallback_category or 'Email delivery failed'
