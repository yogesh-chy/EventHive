"""
apps/orders/urls.py  ·  PHASE 3  (re-aligned to blueprint — Payments)

Routes:
  POST  /api/v1/orders/                   checkout
  GET   /api/v1/orders/                   attendee order list
  GET   /api/v1/orders/{ref}/             order detail
  POST  /api/v1/orders/{ref}/cancel/      cancel (PENDING only)
  POST  /api/v1/orders/{ref}/refund/      refund (CONFIRMED → Stripe refund)
  POST  /api/v1/orders/{ref}/confirm/     manual confirm  [admin / testing]

CHANGE FROM PREVIOUS VERSION:
  <uuid:id> replaced with <str:reference> per blueprint's documented
  endpoint shape: GET /api/v1/orders/{ref}/.

The Stripe webhook is NOT registered here — per the blueprint it lives at
the API root, not nested under /orders/:
  POST /api/v1/webhooks/stripe/
See config/urls.py for that route.
"""

from django.urls import path, re_path
from .views import OrderViewSet

order_list    = OrderViewSet.as_view({"get": "list",     "post": "create"})
order_detail  = OrderViewSet.as_view({"get": "retrieve"})
order_cancel  = OrderViewSet.as_view({"post": "cancel"})
order_refund  = OrderViewSet.as_view({"post": "refund"})
order_confirm = OrderViewSet.as_view({"post": "confirm"})

# References are exactly 8 chars from a restricted alphabet (see
# services.generate_order_reference). re_path with an explicit pattern
# avoids accidentally matching unrelated path segments.
_REF_PATTERN = r"(?P<reference>[A-Z2-9]{8,12})"

urlpatterns = [
    path("",                                order_list,    name="order-list"),
    re_path(rf"^{_REF_PATTERN}/$",          order_detail,  name="order-detail"),
    re_path(rf"^{_REF_PATTERN}/cancel/$",   order_cancel,  name="order-cancel"),
    re_path(rf"^{_REF_PATTERN}/refund/$",   order_refund,  name="order-refund"),
    re_path(rf"^{_REF_PATTERN}/confirm/$",  order_confirm, name="order-confirm"),
]
