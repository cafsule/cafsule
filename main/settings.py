import os
import sys
from pathlib import Path
from datetime import timedelta
from urllib.parse import quote_plus

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


def _get_bool_env(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {'1', 'true', 'yes', 'on'}


def _get_csv_env(name, default=''):
    raw_value = os.getenv(name)
    if raw_value is None:
        raw_value = default
    return [item.strip() for item in raw_value.split(',') if item.strip()]


def _ensure_https_origin(value):
    if not value:
        return value
    if '://' in value:
        return value.replace('http://', 'https://', 1)
    return f'https://{value}'


def _normalize_csrf_origins(values):
    return [_ensure_https_origin(value) for value in values]


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(os.path.join(BASE_DIR, '.env'))  # Load environment variables from .env file

DEBUG = _get_bool_env('DEBUG', 'False')

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-development-key-change-me'
    else:
        raise ImproperlyConfigured('SECRET_KEY must be provided through the environment when DEBUG=False.')

if not DEBUG and SECRET_KEY == 'django-insecure-development-key-change-me':
    raise ImproperlyConfigured('Production SECRET_KEY cannot use the development fallback value.')

if not DEBUG and len(SECRET_KEY) < 50:
    raise ImproperlyConfigured('SECRET_KEY must be at least 50 characters for production security.')

JWT_SIGNING_KEY = os.getenv('JWT_SIGNING_KEY')
if not DEBUG:  # Only enforce the strict requirement in production
    if not JWT_SIGNING_KEY or len(JWT_SIGNING_KEY.encode('utf-8')) < 32:
        raise ImproperlyConfigured('JWT_SIGNING_KEY must be provided through the environment and be at least 32 bytes long.')
else:  # DEBUG mode: provide a dummy value if not set (for collectstatic during build)
    JWT_SIGNING_KEY = JWT_SIGNING_KEY or 'dummy-development-jwt-key-32-bytes-long-enough'

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=int(os.getenv('JWT_ACCESS_TOKEN_LIFETIME_MINUTES', 30))),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=int(os.getenv('JWT_REFRESH_TOKEN_LIFETIME_DAYS', 7))),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': False,
    
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': JWT_SIGNING_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'JWK_URL': None,
    'LEEWAY': 0,
    
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',
    
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'TOKEN_USER_CLASS': 'rest_framework_simplejwt.models.TokenUser',
    
    'JTI_CLAIM': 'jti',
    
    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(minutes=5),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=1),
}

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# SECURITY WARNING: don't run with debug turned on in production!
ALLOWED_HOSTS = _get_csv_env('ALLOWED_HOSTS', 'localhost,127.0.0.1,0.0.0.0')


# Application definition

INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'sales',
    'auth.apps.AuthConfig',
    'inventory',
    'reports',
    'procurement',
    'expenses',
    'rest_framework',
    'pharmacy',
    'medicine',
    'corsheaders',
    'rest_framework_simplejwt.token_blacklist',
    'django.contrib.gis',
]

# Use the custom user model defined in the auth app (app label 'auth_app')
AUTH_USER_MODEL = 'auth_app.User'

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'social_django.middleware.SocialAuthExceptionMiddleware',
]

ROOT_URLCONF = 'main.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'main.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

def _build_database_config():
    """Return a valid PostGIS PostgreSQL database config.

    Prefer DATABASE_URL when it is already set (for Neon, Heroku, Render, etc.).
    Otherwise, build it from the project's existing DB_* variables so local dev and
    Docker share the same configuration without hardcoding credentials in source.
    """
    env_database_url = os.getenv('DATABASE_URL')
    if env_database_url:
        config = dj_database_url.config(
            default=env_database_url,
            conn_max_age=600,
            conn_health_checks=True,
        )
        config['ENGINE'] = 'django.contrib.gis.db.backends.postgis'
        return config

    db_name = os.getenv('DB_NAME')
    db_user = os.getenv('DB_USER')
    db_password = os.getenv('DB_PASSWORD')
    db_host = os.getenv('DB_HOST', '127.0.0.1')
    db_port = os.getenv('DB_PORT', '5432')
    db_sslmode = os.getenv('DB_SSLMODE', 'disable')

    if not all([db_name, db_user, db_password]):
        raise ImproperlyConfigured(
            'Database configuration is missing. Set DATABASE_URL or provide DB_NAME, '
            'DB_USER, DB_PASSWORD. For local PostgreSQL/PostGIS use a URL like: '
            'postgresql://<user>:<password>@127.0.0.1:5432/<database>?sslmode=disable'
        )

    database_url = (
        f'postgresql://{quote_plus(db_user)}:{quote_plus(db_password)}'
        f'@{db_host}:{db_port}/{db_name}?sslmode={db_sslmode}'
    )
    config = dj_database_url.parse(
        database_url,
        conn_max_age=600,
        conn_health_checks=True,
    )
    config['ENGINE'] = 'django.contrib.gis.db.backends.postgis'
    return config


DATABASES = {'default': _build_database_config()}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = os.getenv('STATIC_URL', '/static/')
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
MEDIA_URL = os.getenv('MEDIA_URL', '/media/')
MEDIA_ROOT = BASE_DIR / os.getenv('MEDIA_ROOT', 'media')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'console': {
            'format': '[%(asctime)s] %(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'stream': sys.stdout,
            'formatter': 'console',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO' if DEBUG else 'WARNING',
    },
}


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

# MAILERS = {
#     'default': {
#         'BACKEND': 'django.core.mail.backends.console.EmailBackend',
#     },
# }


# Token Expiry Settings
EMAIL_VERIFICATION_TOKEN_EXPIRY_HOURS = int(os.getenv('EMAIL_VERIFICATION_TOKEN_EXPIRY_HOURS', 24))
PASSWORD_RESET_TOKEN_EXPIRY_HOURS = int(os.getenv('PASSWORD_RESET_TOKEN_EXPIRY_HOURS', 24))

#Email Configuration

EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 25))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'False').lower() == 'true'
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() == 'true'
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@pharmacy-ims.com')

# OAuth Configuration

SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = os.getenv('GOOGLE_CLIENT_ID', '')
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')
SOCIAL_AUTH_GOOGLE_OAUTH2_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', '')

# Rate Limiting
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '10/minute',
        'user': '60/minute',
        'register': '5/hour',
        'login': '10/minute',
        'password_reset': '3/hour',
        'email_verification': '5/hour',
    },
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

# Development (simple)
CORS_ALLOW_ALL_ORIGINS = _get_bool_env('CORS_ALLOW_ALL_ORIGINS', 'False')

# Or more securely (recommended)
CORS_ALLOWED_ORIGINS = _get_csv_env(
    'CORS_ALLOWED_ORIGINS',
    'https://localhost:3000,https://localhost:5173,https://localhost:8000,https://127.0.0.1:3000,https://127.0.0.1:5173,https://127.0.0.1:8000,https://cafsule.com,https://www.cafsule.com'
)
CSRF_TRUSTED_ORIGINS = _normalize_csrf_origins(
    _get_csv_env(
        'CSRF_TRUSTED_ORIGINS',
        'https://localhost:3000,https://localhost:5173,https://localhost:8000,https://127.0.0.1:3000,https://127.0.0.1:5173,https://127.0.0.1:8000,https://cafsule.com,https://www.cafsule.com,https://api.cafsule.com'
    )
)

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _get_bool_env('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'False')
SECURE_HSTS_PRELOAD = _get_bool_env('SECURE_HSTS_PRELOAD', 'False')
SECURE_CONTENT_TYPE_NOSNIFF = _get_bool_env('SECURE_CONTENT_TYPE_NOSNIFF', 'True')
X_FRAME_OPTIONS = 'DENY'

# Jazzmin configuration
JAZZMIN_SETTINGS = {
    'site_title': 'Cafsule Admin',
    'site_header': 'Cafsule',
    'site_brand': 'Cafsule Pharmacy',
    'welcome_sign': 'Welcome to Cafsule Admin',
    'show_sidebar': True,
    'navigation_expanded': True,
    'hide_apps': [],
    'hide_models': [],
    'order_with_respect_to': [
        'auth_app',
        'sales',
        'inventory',
        'procurement',
        'expenses',
        'pharmacy',
        'medicine',
        'reports',
    ],
    'icons': {
        'auth_app.user': 'fas fa-user',
        'sales.sale': 'fas fa-cash-register',
        'inventory.inventorybatch': 'fas fa-boxes',
        'procurement.purchase': 'fas fa-file-invoice-dollar',
        'pharmacy.pharmacybrand': 'fas fa-clinic-medical',
        'medicine.medicine': 'fas fa-pills',
    },
    'custom_css': 'custom_glass.css',
    'custom_js': None,
    'show_ui_builder': False,
    'language_chooser': False,
}

JAZZMIN_UI_TWEAKS = {
    'theme': 'flatly',
    'accent': 'accent-primary',
    'navbar': 'navbar-white navbar-light',
    'sidebar': 'sidebar-dark-primary',
    'sidebar_nav_flat_style': True,
    'sidebar_nav_legacy_style': False,
    'sidebar_nav_compact_style': False,
    'brand_colour': 'navbar-light',
    'button_classes': {
        'primary': 'btn-primary',
        'secondary': 'btn-secondary',
        'info': 'btn-info',
        'warning': 'btn-warning',
        'danger': 'btn-danger',
        'success': 'btn-success',
    },
}

# Celery Configuration
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'memory://')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'db+sqlite:///celery-results.db')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes
CELERY_TASK_ALWAYS_EAGER = os.getenv('CELERY_TASK_ALWAYS_EAGER', 'True').lower() == 'true'  # Synchronous execution by default
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'


