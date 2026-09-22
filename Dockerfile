FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=main.settings \
    PORT=7860

WORKDIR /app

# System dependencies required for PostGIS, psycopg2, and image handling.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    libproj-dev \
    binutils \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/appuser appuser \
    && chown -R appuser:appgroup /app \
    && chmod -R u+rwX /app \
    && DEBUG=1 SECRET_KEY=collectstatic-only-key python manage.py collectstatic --noinput --clear

USER appuser

EXPOSE 7860

CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn main.wsgi:application --bind 0.0.0.0:7860 --workers 2 --timeout 120"]