"""
config/settings/phase3_additions.py  ·  PHASE 3  (re-aligned to blueprint — Payments)

Paste these into config/settings/base.py.

CHANGES FROM PREVIOUS VERSION:
  Added Stripe configuration block. Per blueprint's .env reference (page 16):
    STRIPE_SECRET_KEY=sk_test_...
    STRIPE_WEBHOOK_SECRET=whsec_...
    STRIPE_PUBLISHABLE_KEY=pk_test_...
  These MUST come from environment variables (python-decouple), never
  hardcoded — the blueprint explicitly calls out ".env file (never committed
  to git)" as the pattern for all secrets.
"""

# ── 1. INSTALLED_APPS addition ────────────────────────────────────────────────
# Add after "apps.events":
#   "apps.orders",

# ── 2. Stripe ──────────────────────────────────────────────────────────────────
# pip install stripe
from decouple import config as _env  # python-decouple, per blueprint tech stack

STRIPE_SECRET_KEY      = _env("STRIPE_SECRET_KEY", default="")
STRIPE_PUBLISHABLE_KEY = _env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_WEBHOOK_SECRET   = _env("STRIPE_WEBHOOK_SECRET", default="")

# ── 3. Celery ──────────────────────────────────────────────────────────────────
# pip install "celery[beat]>=5.3" django-celery-beat

CELERY_BROKER_URL      = "redis://redis:6379/1"
CELERY_RESULT_BACKEND  = "redis://redis:6379/1"
CELERY_ACCEPT_CONTENT  = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_TIMEZONE        = "UTC"

CELERY_BEAT_SCHEDULE = {
    "expire-pending-orders": {
        "task":     "apps.orders.tasks.expire_pending_orders_task",
        "schedule": 120,   # every 2 minutes
    },
}

# ── 4. New requirements to add to requirements/base.txt ───────────────────────
PHASE_3_REQUIREMENTS = """
stripe>=8.0
celery[beat]>=5.3
django-celery-beat>=2.5
redis>=5.0
python-decouple>=3.8
"""
# pip install stripe "celery[beat]>=5.3" django-celery-beat redis python-decouple

# ── 5. Migration run order ─────────────────────────────────────────────────────
# python manage.py migrate users
# python manage.py migrate organizations
# python manage.py migrate events         (0001_initial + 0002_search_vector_trigger)
# python manage.py migrate orders         (0001_initial + 0002_phase3_payments)

# ── 6. Stripe CLI for local webhook testing ───────────────────────────────────
# stripe listen --forward-to localhost:8000/api/v1/webhooks/stripe/
# This prints a webhook signing secret — set it as STRIPE_WEBHOOK_SECRET in .env
# for local development; it differs from your Dashboard webhook secret.
