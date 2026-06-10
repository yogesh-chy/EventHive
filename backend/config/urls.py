from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.users.urls import auth_urlpatterns, user_urlpatterns

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

    # API Schema
    path('api/v1/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/v1/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
