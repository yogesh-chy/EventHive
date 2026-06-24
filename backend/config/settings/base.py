from datetime import timedelta
from pathlib import Path
import dj_database_url

from decouple import Csv, config

# ---- Paths ----
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---- Security ----
SECRET_KEY = config("DJANGO_SECRET_KEY", default=config("SECRET_KEY", default="django-insecure-dev-key"))
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# ---- Application definition ----
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
    "django_filters",
    "drf_spectacular",
]

LOCAL_APPS = [
    "core",
    "apps.users",
    "apps.organizations",
    "apps.events",
    "apps.audit",
    "apps.orders",
    "apps.tickets",
    "apps.notifications",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---- Middleware ----
MIDDLEWARE = [
    "core.middleware.RequestIDMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.StructuredRequestLogMiddleware",
    "core.middleware.AuditContextMiddleware",
    "core.middleware.QueryTimingMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# ---- Templates ----
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

# ---- Database ----
DATABASES = {
    "default": dj_database_url.config(
        default=f"postgres://{config('POSTGRES_USER', default='eventhive')}:{config('POSTGRES_PASSWORD', default='Secret@123')}@{config('POSTGRES_HOST', default='localhost')}:{config('POSTGRES_PORT', default='5432')}/{config('POSTGRES_DB', default='eventhive')}",
        conn_max_age=60,
    )
}

# ---- Custom User Model ----
AUTH_USER_MODEL = "users.User"

# ---- Password validation ----
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---- Internationalisation ----
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---- Static & Media ----
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---- Cache (Redis) ----
REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "db": "0",
        },
        "KEY_PREFIX": "eventhive",
        "TIMEOUT": 300,
    }
}

# ---- Celery ----
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60

CELERY_BEAT_SCHEDULE = {
    "expire-pending-orders": {
        "task":     "apps.orders.tasks.expire_pending_orders_task",
        "schedule": 120,   # every 2 minutes
    },
    "dispatch-event-reminders": {
        "task":     "tasks.notifications.dispatch_event_reminders_task",
        "schedule": 900,   # every 15 minutes
    },
    "dispatch-abandoned-cart-emails": {
        "task":     "tasks.notifications.dispatch_abandoned_cart_emails_task",
        "schedule": 120,   # every 2 minutes -- same cadence as expiry, see services.py
    },
}

CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {
    "tasks.tickets.generate_ticket_assets_task": {"queue": "assets"},
    "tasks.notifications.send_ticket_confirmation_email_task": {"queue": "emails"},
    "tasks.notifications.send_event_reminder_email_task": {"queue": "emails"},
    "tasks.notifications.send_abandoned_cart_email_task": {"queue": "emails"},
    # Beat dispatcher tasks and apps.orders.tasks.expire_pending_orders_task
    # stay on "default" -- they're lightweight queries that just fan out,
    # not the actual heavy work.
}

CELERY_IMPORTS = (
    "tasks.tickets",
    "tasks.notifications",
)

# ---- Stripe ----
STRIPE_SECRET_KEY      = config("STRIPE_SECRET_KEY", default="")
STRIPE_PUBLISHABLE_KEY = config("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_WEBHOOK_SECRET   = config("STRIPE_WEBHOOK_SECRET", default="")

# ---- AWS ----
AWS_ACCESS_KEY_ID       = config("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY   = config("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME", default="eventhive-assets")
AWS_S3_REGION_NAME      = config("AWS_S3_REGION_NAME", default="auto")
AWS_S3_ENDPOINT_URL     = config("AWS_S3_ENDPOINT_URL", default="") or None

# ---- Notifications timing ----
TICKET_PDF_LINK_TTL_SECONDS = config("TICKET_PDF_LINK_TTL_SECONDS", default=259200, cast=int)
ABANDONED_CART_AFTER_MINUTES = config("ABANDONED_CART_AFTER_MINUTES", default=6, cast=int)

# ---- Django REST Framework ----
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
        "auth": "10/minute",
    },
    "DEFAULT_PAGINATION_CLASS": "core.pagination.EventCursorPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# ---- JWT Settings ----
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
}

# ---- CORS ----
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000",
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True


# ---- Email ----
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@eventhive.io")
EMAIL_VERIFICATION_EXPIRY_HOURS = 24

# ---- Frontend URL ----
FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:3000")

# ---- OpenAPI / Swagger ----
SPECTACULAR_SETTINGS = {
    "TITLE": "EventHive API",
    "DESCRIPTION": "Multi-Tenant Event Ticketing Platform",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---- Logging ----
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
