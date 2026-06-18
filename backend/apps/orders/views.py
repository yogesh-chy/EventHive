import logging

from django.core.cache import cache
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.cache import ORDER_DETAIL_TTL, invalidate_order_cache, order_detail_key
from core.exceptions import InsufficientInventoryError, InvalidStatusTransitionError, OrderAlreadyConfirmedError, OrderExpiredError
from core.mixins import AttendeeOrderMixin
from core.pagination import StandardPagePagination
from core.permissions import IsAdminUser, IsOrderOwner

from . import services
from .filters import OrderFilter
from .models import Order
from .serializers import OrderCreateSerializer, OrderDetailSerializer, OrderListSerializer
from .services import CheckoutItem

logger = logging.getLogger(__name__)

_CONFLICT_EXCEPTIONS = (
    InsufficientInventoryError,
    InvalidStatusTransitionError,
    OrderAlreadyConfirmedError,
    OrderExpiredError)


# ---- Queryset Helpers -----
def _base_qs():
    return(Order.objects.filter(is_deleted=False).select_related("event", "event__org", "attendee"))

def _detail_qs():
    return _base_qs().prefetch_related("items__tier", "items__tickets")


# ---- ViewSet ----
class OrderViewSet(AttendeeOrderMixin, viewsets.GenericViewSet):
    lookup_field = "id"
    pagination_class = StandardPagePagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = OrderFilter
    ordering_fields = ["created_at", "total_amount", "status"]
    ordering = ["-created_at"]

    def get_permissions(self):
        if self.action in ("retrieve", "cancel"):
            return [IsAuthenticated(), IsOrderOwner()]
        if self.action == "confirm":
            # Phase 4: replace with Stripe webhook secret validation.
            return [IsAuthenticated(), IsAdminUser()]
        return [IsAuthenticated()]
    
    def get_queryset(self):
        qs = _detail_qs() if self.action == "retrieve" else _base_qs()
        return self.apply_attendee_scope(qs)
    
    # --- Create Order ---
    def create(self, request):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        event = serializer.validated_data["event"]
        items = [
            CheckoutItem(tier_id=i["tier_id"], quantity=i["quantity"])
            for i in serializer.validated_data["items"]
        ]

        try:
            order = services.create_order(
                attendee=request.user,
                event=event,
                items=items
            )
        except _CONFLICT_EXCEPTIONS as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_409_CONFLICT)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        
        full = _detail_qs().get(pk=order.pk)
        return Response(OrderDetailSerializer(full).data, status=status.HTTP_201_CREATED)


    # --- Get All Orders ---
    def list(self, request):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(OrderListSerializer(page, many=True).data)
        return Response(OrderListSerializer(qs, many=True).data)


    # --- Get Specific Orders ---
    def retrieve(self, request, id=None):
        cache_key = order_detail_key(str(id))
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        order = self.get_object()
        data = OrderDetailSerializer(order).data
        cache.set(cache_key, data, ORDER_DETAIL_TTL)
        return Response(data)
    
    # --- Cancel an Order ----
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, id=None):
        order = self.get_object()
        try:
            updated = services.cancel_order(order=order, actor=request.user)
        except _CONFLICT_EXCEPTIONS as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_409_CONFLICT)
        invalidate_order_cache(str(updated.id))
        return Response(OrderDetailSerializer(_detail_qs().get(pk=updated.pk)).data)
    

    # --- Confirm an Order ---
    # Phase 4: this is replaced by the Stripe webhook handler.
    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, id=None):
        order = self.get_object()
        payment_intent_id = request.data.get("payment_intent_id", request.data.get("payment_intend_id", ""))
        try:
            updated = services.confirm_order(order=order, payment_intent_id=payment_intent_id)
        except _CONFLICT_EXCEPTIONS as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_409_CONFLICT)
        invalidate_order_cache(str(updated.id))
        return Response(OrderDetailSerializer(_detail_qs().get(pk=updated.pk)).data)