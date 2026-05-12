from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # API Schema
    path('api/v1/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/v1/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    
    # Apps (to be implemented)
    # path('api/v1/auth/', include('apps.users.urls')),
    # path('api/v1/orgs/', include('apps.organizations.urls')),
    # path('api/v1/events/', include('apps.events.urls')),
    # path('api/v1/orders/', include('apps.orders.urls')),
]
