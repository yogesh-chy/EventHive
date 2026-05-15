# config/settings/dev.py — Local development overrides
from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

# In dev, use console email backend so we can see verification tokens
# without needing a real SMTP server
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Allow all origins in dev (override in prod)
CORS_ALLOW_ALL_ORIGINS = True

# Silk / django-silk for query profiling (install in dev deps)
INSTALLED_APPS += ["silk"]  # noqa: F405
MIDDLEWARE += ["silk.middleware.SilkyMiddleware"]  # noqa: F405

# Lower throttle rates so dev / tests aren't blocked
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {  # noqa: F405
    "anon": "1000/minute",
    "user": "1000/minute",
    "auth": "100/minute",
}

# Expose DB queries for QueryTimingMiddleware
SLOW_QUERY_THRESHOLD_MS = 50
MAX_QUERIES_PER_REQUEST = 20
