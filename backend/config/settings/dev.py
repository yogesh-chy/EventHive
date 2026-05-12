from .base import *
import dj_database_url

DEBUG = True

ALLOWED_HOSTS = ['*']

# Database
DATABASES = {
    'default': dj_database_url.config(
        default=config('DATABASE_URL')
    )
}

# Email Backend for Dev
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# CORS
CORS_ALLOW_ALL_ORIGINS = True
