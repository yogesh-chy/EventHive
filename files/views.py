"""
apps/orders/views.py  ·  PHASE 3  (re-aligned to blueprint — Payments)

CHANGES FROM PREVIOUS VERSION:
  - lookup_field changed from "id" to "reference" — blueprint specifies
    GET /api/v1/orders/{ref}/ and POST /api/v1/orders/{ref}/cancel/.
  - create() now performs the full blueprint purchase flow:
      1. services.create_order()             — DB transaction, no Stripe
      2. payment.create_payment_intent()      — Stripe call, outside the DB transaction
      3. services.attach_payment_intent()     — record the intent id
      4. on Stripe failure: services.cancel_order() to roll back inventory,
         return 402 Payment Required (matches blueprint: "On failure:
         rollback DB transaction, release Redis lock, return 402.")
    Response includes client_secret so the frontend can complete payment
    via Stripe.js / Stripe Elements.
  - Added refund action: POST /api/v1/orders/{ref}/refund/.
  - confirm action kept for admin/manual testing; Stripe webhook
    (webhook_views.py) is now the PRIMARY confirmation path in production.

PREDICTED PROBLEMS ADDRESSED:
  1. N+1 on list/detail → select_related + prefetch_related, as before.
  2. Attendee seeing another user's orders → AttendeeOrderMixin scope.
  3. Service/payment exceptions returning 500 → mapped to 409/402/502.
  4. PARTIAL FAILURE BETWEEN DB COMMIT AND STRIPE CALL — if Stripe's
     create_payment_intent() call fails (network error, card validation,
     etc.) AFTER create_order() has already committed and decremented
     inventory, the inventory must be restored. cancel_order() is called
     in the except block specifically to undo this — the user sees a 402,
     not a successful order that nobody charged for and that silently
     consumed inventory forever.
  5. CLIENT_SECRET LEAKING TO THE WRONG USER — client_secret is only
     returned in the immediate create() response, never persisted into
     the cached OrderDetailSerializer payload (cache stores model fields
     only, not the ephemeral Stripe response).
"""

import logging

from django.core.cache import cache
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.cache import ORDER_DETAIL_TTL, invalidate_order_cache, order_detail_key
from core.exceptions import (
    InsufficientInventoryError,
    InvalidStatusTransitionError,
    OrderAlreadyConfirmedError,
    OrderExpiredError,
    PaymentFailedError,
    RefundFailedError,
)
from core.mixins import AttendeeOrderMixin
from core.pagination import StandardPagePagination
from core.permissions import IsAdminUser, IsOrderOwner

from . import payment, services
from .filters import OrderFilter
from .models import Order
from .serializers import (
    OrderCreateSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
)
from .services import CheckoutItem

logger = logging.getLogger(__name__)

_CONFLICT_EXCEPTIONS = (
    InsufficientInventoryError,
    InvalidStatusTransitionError,
    OrderAlreadyConfirmedError,
    OrderExpiredError,
)


def _base_qs():
    return (
        Order.objects.filter(is_deleted=False)
        .select_related("event", "event__org", "attendee")
    )


def _detail_qs():
    return _base_qs().prefetch_related("items__tier", "items__tickets")


class OrderViewSet(AttendeeOrderMixin, viewsets.GenericViewSet):
    """
    POST   /api/v1/orders/                  checkout
    GET    /api/v1/orders/                  attendee's order list
    GET    /api/v1/orders/{ref}/            order detail
    POST   /api/v1/orders/{ref}/cancel/     cancel order (PENDING only, no Stripe call)
    POST   /api/v1/orders/{ref}/refund/     refund order (CONFIRMED → Stripe refund)
    POST   /api/v1/orders/{ref}/confirm/    manual confirm  [admin / testing only]
    """

    lookup_field     = "reference"
    pagination_class = StandardPagePagination
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class  = OrderFilter
    ordering_fields  = ["created_at", "total_amount", "status"]
    ordering         = ["-created_at"]

    def get_permissions(self):
        if self.action in ("retrieve", "cancel", "refund"):
            return [IsAuthenticated(), IsOrderOwner()]
        if self.action == "confirm":
            return [IsAuthenticated(), IsAdminUser()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = _detail_qs() if self.action == "retrieve" else _base_qs()
        return self.apply_attendee_scope(qs)

    # ── POST /api/v1/orders/ ───────────────────────────────────────────────────

    def create(self, request):
        """
        Checkout. Full flow per blueprint "Atomic Ticket Purchase":
          1. Validate + create PENDING order (DB transaction, inventory decremented)
          2. Create Stripe PaymentIntent (outside the DB transaction)
          3. Attach the PaymentIntent id to the order
          4. Return order detail + client_secret

        On Stripe failure: roll back by cancelling the order (restores
        inventory, releases seat lock) and return 402.

        Request body:
          {
            "event_slug": "my-event",
            "items": [{"tier_id": "<uuid>", "quantity": 2}]
          }
        """
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        event = serializer.validated_data["event"]
        items = [
            CheckoutItem(tier_id=i["tier_id"], quantity=i["quantity"])
            for i in serializer.validated_data["items"]
        ]

        # ── Step 1: DB transaction — create order, decrement inventory ────────
        try:
            order = services.create_order(attendee=request.user, event=event, items=items)
        except _CONFLICT_EXCEPTIONS as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_409_CONFLICT)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # ── Step 2: Stripe PaymentIntent — outside the DB transaction ─────────
        try:
            intent = payment.create_payment_intent(order)
        except PaymentFailedError as exc:
            # Roll back: inventory was already decremented in step 1.
            # cancel_order() restores it and releases the seat lock.
            services.cancel_order(order=order, actor=request.user)
            return Response({"detail": str(exc.detail)}, status=status.HTTP_402_PAYMENT_REQUIRED)

        # ── Step 3: record the PaymentIntent id ───────────────────────────────
        order = services.attach_payment_intent(order=order, stripe_payment_intent_id=intent.id)

        full = _detail_qs().get(pk=order.pk)
        data = OrderDetailSerializer(full).data
        data["client_secret"] = intent.client_secret  # needed by Stripe.js, never cached
        return Response(data, status=status.HTTP_201_CREATED)

    # ── GET /api/v1/orders/ ────────────────────────────────────────────────────

    def list(self, request):
        qs   = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(OrderListSerializer(page, many=True).data)
        return Response(OrderListSerializer(qs, many=True).data)

    # ── GET /api/v1/orders/{ref}/ ──────────────────────────────────────────────

    def retrieve(self, request, reference=None):
        cache_key = order_detail_key(reference)
        cached    = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        order = self.get_object()
        data  = OrderDetailSerializer(order).data
        cache.set(cache_key, data, ORDER_DETAIL_TTL)
        return Response(data)

    # ── POST /api/v1/orders/{ref}/cancel/ ──────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, reference=None):
        """
        Cancel a PENDING order. Does NOT call Stripe — if the order is
        CONFIRMED (money already moved), this raises OrderAlreadyConfirmedError;
        the client should call /refund/ instead.
        """
        order = self.get_object()
        try:
            updated = services.cancel_order(order=order, actor=request.user)
        except _CONFLICT_EXCEPTIONS as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_409_CONFLICT)
        invalidate_order_cache(updated.reference)
        return Response(OrderDetailSerializer(_detail_qs().get(pk=updated.pk)).data)

    # ── POST /api/v1/orders/{ref}/refund/ ──────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="refund")
    def refund(self, request, reference=None):
        """
        Refund a CONFIRMED order: Stripe refund, then inventory restoration
        and status → REFUNDED.
        """
        order = self.get_object()
        try:
            updated = services.refund_order(order=order, actor=request.user)
        except _CONFLICT_EXCEPTIONS as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_409_CONFLICT)
        except RefundFailedError as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_502_BAD_GATEWAY)

        invalidate_order_cache(updated.reference)
        return Response(OrderDetailSerializer(_detail_qs().get(pk=updated.pk)).data)

    # ── POST /api/v1/orders/{ref}/confirm/  [admin/testing only] ──────────────

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, reference=None):
        """
        Manually confirm a PENDING order. Restricted to admins.
        In production, the Stripe webhook (webhook_views.stripe_webhook) is
        the real confirmation path — this exists for testing without a live
        Stripe webhook configured.
        """
        order             = self.get_object()
        payment_intent_id = request.data.get("payment_intent_id", "")
        try:
            updated = services.confirm_order(order=order, payment_intent_id=payment_intent_id)
        except _CONFLICT_EXCEPTIONS as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_409_CONFLICT)
        invalidate_order_cache(updated.reference)
        return Response(OrderDetailSerializer(_detail_qs().get(pk=updated.pk)).data)
