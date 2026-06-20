from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.users.urls import auth_urlpatterns, user_urlpatterns
from apps.orders.webhook_views import stripe_webhook

urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth  (POST register, login, logout, verify-email, token/refresh)
    path('api/v1/auth/', include(auth_urlpatterns)),
    # Users (GET/PATCH me/)
    path('api/v1/users/', include(user_urlpatterns)),
    # Organizations
    path('api/v1/orgs/', include('apps.organizations.urls')),
    # Events & Ticket Tiers
    path('api/v1/events/', include('apps.events.urls')),
    # Orders & Tickets
    path('api/v1/orders/', include('apps.orders.urls')),
    # Stripe Webhook
    path('api/v1/webhooks/stripe/', stripe_webhook, name='stripe-webhook'),

    # API Schema
    path('api/v1/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/v1/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
