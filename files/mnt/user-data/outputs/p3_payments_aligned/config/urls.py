"""
config/urls.py  ·  ALL PHASES  (re-aligned to blueprint — adds Stripe webhook)

CHANGE FROM PREVIOUS VERSION:
  Added POST /api/v1/webhooks/stripe/ per blueprint's API reference (page 10):
    "POST /api/v1/webhooks/stripe/   Stripe   Payment confirmed / failed webhook"
  This route is registered directly here, NOT inside apps/orders/urls.py,
  because it sits at /api/v1/webhooks/ rather than /api/v1/orders/ —
  matching the blueprint's URL structure exactly.
"""

from django.contrib import admin
from django.urls import include, path

from apps.orders.webhook_views import stripe_webhook

urlpatterns = [
    path("admin/", admin.site.urls),

    # Phase 1
    path("api/v1/auth/",   include("apps.users.urls")),
    path("api/v1/users/",  include("apps.users.profile_urls")),
    path("api/v1/orgs/",   include("apps.organizations.urls")),

    # Phase 2
    path("api/v1/events/", include("apps.events.urls")),

    # Phase 3
    path("api/v1/orders/", include("apps.orders.urls")),
    path("api/v1/webhooks/stripe/", stripe_webhook, name="stripe-webhook"),

    # Schema
    path("api/v1/schema/", include("drf_spectacular.urls")),
]
