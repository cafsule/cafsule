# Email delivery and Celery

Cafsule sends OTP email through `auth.tasks.send_otp_email`. Registration invokes the task directly, so that email is sent inline by the web process. OTP requests (including resend requests through `/api/auth/otp/request/`) use the existing safe task helper and queue work with Celery. If publishing fails, that helper falls back to in-process execution. A successful OTP request response otherwise means the task was accepted for dispatch; a worker must consume it to send the message.

## Local host setup

The host `.env` should point `CELERY_BROKER_URL` at `redis://localhost:6379/0`, and SMTP values should use the configured Gmail account and intended `DEFAULT_FROM_EMAIL`. Start Redis, then start a worker from the project root using the same virtual environment and `.env` as Django:

```sh
docker compose up -d redis
.venv/bin/celery -A main worker --loglevel=info
```

Run Django in a separate terminal with the same environment. Stop the worker with Ctrl+C.

## Docker Compose

Compose runs Redis and a `celery` worker using the same `.env` file as the web service, with container-local database and Redis hostnames. Start the stack with:

```sh
docker compose up -d db redis web celery
```

View task execution with `docker compose logs -f celery`.

## Safe SMTP delivery diagnostic

The command first checks DNS and TCP connectivity to the configured SMTP host/port (using the bounded `EMAIL_TIMEOUT`), then opens Django's SMTP connection (including configured STARTTLS/SSL and authentication). Gmail on port 587 requires `EMAIL_USE_TLS=True`. Without `--recipient`, it sends no email. With an explicit test mailbox, it sends one harmless message. Failures report exception class names and a safe category only; SMTP responses, credentials, and environment values are not logged.

```sh
.venv/bin/python manage.py email_diagnostic
.venv/bin/python manage.py email_diagnostic --recipient you-control@example.com
```

A success means the SMTP server accepted the message for submission; it cannot guarantee inbox placement. Gmail must have the custom `DEFAULT_FROM_EMAIL` configured as a permitted send-as alias if the authenticated Gmail account differs. That alias is an external Gmail/domain setting.

To test Railway's network path, use an authenticated Railway shell/SSH session for the backend service and run `python manage.py email_diagnostic` there. Do not use `railway run` from a local workstation to infer Railway connectivity: that runs the command locally. Do not expose a public diagnostic endpoint. If the one-off check succeeds locally but DNS or TCP fails in Railway, SMTP egress is blocked or unavailable from that runtime; use an HTTPS/API-based transactional email provider rather than changing Gunicorn timeouts or repeatedly altering Gmail settings.
