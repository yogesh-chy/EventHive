from .base import *

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

CORS_ALLOW_ALL_ORIGINS = True

INSTALLED_APPS += ["silk"]
MIDDLEWARE += ["silk.middleware.SilkyMiddleware"]


REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "user": "1000/minute",
    "auth": "100/minute",
}

SLOW_QUERY_THRESHOLD_MS = 50
MAX_QUERIES_PER_REQUEST = 20
