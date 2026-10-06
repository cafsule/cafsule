import smtplib
import ssl

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Submit a harmless diagnostic email through the configured SMTP backend."

    def add_arguments(self, parser):
        parser.add_argument(
            "--recipient", required=True, help="Test mailbox address controlled by the operator."
        )

    def handle(self, *args, **options):
        if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
            raise CommandError("EMAIL_BACKEND is not Django SMTP EmailBackend.")

        connection = get_connection(fail_silently=False)
        try:
            try:
                connection.open()
            except Exception as exc:
                self._report_failure("connection/authentication/TLS", exc)
                raise CommandError("SMTP connection setup failed.") from exc

            message = EmailMessage(
                subject="Cafsule SMTP delivery diagnostic",
                body="This is a harmless SMTP delivery diagnostic message.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[options["recipient"]],
                connection=connection,
            )
            try:
                sent = message.send(fail_silently=False)
            except Exception as exc:
                self._report_failure("message submission/sender/recipient", exc)
                raise CommandError("SMTP message submission failed.") from exc

            if sent != 1:
                raise CommandError("SMTP backend did not submit the diagnostic message.")
            self.stdout.write(self.style.SUCCESS(
                "SMTP accepted the diagnostic message for submission. This does not confirm inbox delivery."
            ))
        finally:
            connection.close()

    def _report_failure(self, stage, exc):
        message = str(exc)
        if settings.EMAIL_HOST_PASSWORD:
            message = message.replace(settings.EMAIL_HOST_PASSWORD, "[REDACTED]")
        if isinstance(exc, smtplib.SMTPAuthenticationError):
            stage = "SMTP authentication"
        elif isinstance(exc, smtplib.SMTPSenderRefused):
            stage = "sender rejection"
        elif isinstance(exc, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
            stage = "TLS negotiation"
        elif isinstance(exc, (smtplib.SMTPConnectError, OSError, TimeoutError)):
            stage = "SMTP connection"
        self.stderr.write(f"{stage} failed ({type(exc).__name__}): {message}")
