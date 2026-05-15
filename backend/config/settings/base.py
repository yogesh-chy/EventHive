"""
config/settings/base.py — Shared settings for all environments.

SENIOR DEV NOTES / PREDICTED PROBLEMS:
─────────────────────────────────────────────────────────────────────────────
1. SECRET_KEY must NEVER have a hardcoded default. If env var is missing,
   raise ImproperlyConfigured immediately at startup — don't silently use
   a weak key.

2. INSTALLED_APPS order matters:
   - 'django.contrib.contenttypes' must come before auth apps.
   - 'corsheaders' middleware must be FIRST in MIDDLEWARE list.
   - 'rest_framework_simplejwt.token_blacklist' requires its own migration.

3. AUTH_USER_MODEL must be set BEFORE the first migration. Changing it
   after migrations exist requires squashing or recreation — very painful.

4. DEFAULT_AUTO_FIELD: Set to BigAutoField globally to avoid per-model
   warnings in Django 3.2+. Our BaseModel overrides this with UUID anyway.

5. CONN_MAX_AGE = 60: persistent DB connections reduce TCP overhead in
   production. But in a multi-process Gunicorn setup, each worker gets
   its own connection pool. Don't set too high — idle connections consume
   Postgres resources.
─────────────────────────────────────────────────────────────────────────────
"""

import os
from pathlib import Path

from decouple import Csv, config

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ─── Security ─────────────────────────────────────────────────────────────────
SECRET_KEY = config("SECRET_KEY")  # No default — fail loudly if missing
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# ─── Application definition ───────────────────────────────────────────────────
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",              # OpenAPI / Swagger docs
]

LOCAL_APPS = [
    "core",
    "apps.users",
    "apps.organizations",
    # Phase 2+
    # "apps.events",
    # "apps.orders",
    # "apps.tickets",
    # "apps.notifications",
    # "apps.audit",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ─── Middleware ────────────────────────────────────────────────────────────────
# PREDICTED PROBLEM: CorsMiddleware MUST be before CommonMiddleware.
# AuditContextMiddleware MUST be after AuthenticationMiddleware so
# request.user is available.
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",                   # 1st
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # resolves user
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.AuditContextMiddleware",                   # after auth
    "core.middleware.QueryTimingMiddleware",                    # dev only (checks DEBUG)
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ─── Templates ────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ─── Database ─────────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("POSTGRES_DB", default="eventhive"),
        "USER": config("POSTGRES_USER", default="eventhive"),
        "PASSWORD": config("POSTGRES_PASSWORD"),
        "HOST": config("POSTGRES_HOST", default="localhost"),
        "PORT": config("POSTGRES_PORT", default="5432"),
        "CONN_MAX_AGE": 60,   # persistent connections
    }
}

# ─── Custom User Model ────────────────────────────────────────────────────────
# MUST be set before the first migration — never change after data exists.
AUTH_USER_MODEL = "users.User"

# ─── Password validation ──────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─── Internationalisation ─────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ─── Static & Media ───────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── Cache (Redis) ────────────────────────────────────────────────────────────
REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "db": "0",
        },
        "KEY_PREFIX": "eventhive",
        "TIMEOUT": 300,  # 5 minutes default TTL
    }
}

# ─── Django REST Framework ────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",  # for file uploads
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/minute",
        "user": "300/minute",
        "auth": "10/minute",    # tighter limit for login/register
    },
    "DEFAULT_PAGINATION_CLASS": "core.pagination.CursorPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# ─── JWT Settings ─────────────────────────────────────────────────────────────
from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,          # new refresh on every use
    "BLACKLIST_AFTER_ROTATION": True,       # old refresh is blacklisted
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
}

# ─── CORS ─────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000",
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True

# ─── Email ────────────────────────────────────────────────────────────────────
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@eventhive.io")
EMAIL_VERIFICATION_EXPIRY_HOURS = 24

# ─── Frontend URL (used in email links) ──────────────────────────────────────
FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:3000")

# ─── OpenAPI / Swagger ────────────────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    "TITLE": "EventHive API",
    "DESCRIPTION": "Multi-Tenant Event Ticketing Platform",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ─── Logging ──────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": config("DJANGO_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}
