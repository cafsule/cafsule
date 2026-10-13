import smtplib

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand, CommandError

from main.email_utils import email_failure_category


class Command(BaseCommand):
    help = "Check configured SMTP connectivity, optionally sending one diagnostic email."

    def add_arguments(self, parser):
        parser.add_argument(
            "--recipient",
            help="Optional test mailbox address controlled by the operator.",
        )

    def handle(self, *args, **options):
        self.stdout.write(f"Email backend: {settings.EMAIL_BACKEND}")
        self.stdout.write(f"SMTP host: {settings.EMAIL_HOST}")
        self.stdout.write(f"SMTP port: {settings.EMAIL_PORT}")
        self.stdout.write(f"TLS enabled: {settings.EMAIL_USE_TLS}")
        self.stdout.write(f"SSL enabled: {settings.EMAIL_USE_SSL}")

        if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
            raise CommandError("EMAIL_BACKEND is not Django SMTP EmailBackend.")
        if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
            raise CommandError("SMTP configuration cannot enable TLS and SSL together.")

        connection = get_connection(
            fail_silently=False,
            timeout=settings.EMAIL_TIMEOUT,
        )
        try:
            try:
                connection.open()
            except Exception as exc:
                self._report_failure("SMTP connection/authentication", exc)
                raise CommandError(
                    f"SMTP setup failed: {email_failure_category(exc)}."
                ) from None

            self.stdout.write(self.style.SUCCESS(
                "SMTP connection and authentication succeeded."
            ))
            if not options["recipient"]:
                return

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
                self._report_failure("SMTP message submission", exc)
                raise CommandError(
                    f"SMTP submission failed: {email_failure_category(exc)}."
                ) from None

            if sent != 1:
                raise CommandError("SMTP backend did not submit the diagnostic message.")
            self.stdout.write(self.style.SUCCESS(
                "SMTP accepted the diagnostic message for submission. This does not confirm inbox delivery."
            ))
        finally:
            connection.close()

    def _report_failure(self, stage, exc):
        self.stderr.write(
            f"{stage} failed ({type(exc).__name__}): {email_failure_category(exc)}."
        )
