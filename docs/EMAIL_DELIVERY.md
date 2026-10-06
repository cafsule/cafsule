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

The command below requires an explicit test mailbox, sends one harmless message from the configured sender, and reports connection, authentication, TLS, sender rejection, or submission failures without printing the SMTP password:

```sh
.venv/bin/python manage.py email_diagnostic --recipient you-control@example.com
```

A success means the SMTP server accepted the message for submission; it cannot guarantee inbox placement. Gmail must have the custom `DEFAULT_FROM_EMAIL` configured as a permitted send-as alias if the authenticated Gmail account differs. That alias is an external Gmail/domain setting.
