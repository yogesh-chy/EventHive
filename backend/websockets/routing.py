from django.urls import re_path

from .consumers import SeatConsumer

websocket_urlpatterns = [
    re_path(r"^ws/events/(?P<slug>[-\w]+)/seats/$", SeatConsumer.as_asgi()),
]