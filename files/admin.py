"""
apps/orders/admin.py  ·  PHASE 3  (re-aligned to blueprint — Payments)

CHANGES FROM PREVIOUS VERSION:
  - list_display / search_fields use `reference` instead of the raw UUID.
  - stripe_payment_intent_id, idempotency_key, confirmed_at, cancelled_at
    added to readonly_fields — these must only ever be written by
    services.py / payment.py, never edited by hand in the admin (editing
    stripe_payment_intent_id directly could point an order at the wrong
    PaymentIntent).
  - Added a "Refund selected orders" action that calls services.refund_order()
    for each row, so admin-initiated refunds go through the same Stripe +
    inventory-restoration path as the API endpoint — never a raw status edit.

PREDICTED PROBLEMS ADDRESSED:
  1. Admin hand-editing stripe_payment_intent_id → read-only field.
  2. Admin bulk status-editing bypassing the state machine → status field
     stays read-only; refund/cancel actions go through services.py.
  3. Admin hard-deleting orders → delete_selected removed; soft-delete only.
  4. N+1 on order list → select_related + annotate(Count('items')).
"""

from django.contrib import admin
from django.db.models import Count

from . import services
from .models import Order, OrderItem, OrderStatus, Ticket, TicketStatus


class OrderItemInline(admin.TabularInline):
    model           = OrderItem
    extra           = 0
    can_delete      = False
    show_change_link = True
    readonly_fields = ["tier", "quantity", "unit_price", "subtotal_display"]
    fields          = ["tier", "quantity", "unit_price", "subtotal_display"]

    @admin.display(description="Subtotal")
    def subtotal_display(self, obj):
        return f"{obj.subtotal:.2f}"


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display  = [
        "reference", "attendee", "event", "status_badge",
        "total_amount", "currency", "items_count",
        "expires_at", "created_at",
    ]
    list_filter   = ["status", "currency", "event__org"]
    search_fields = ["reference", "attendee__email", "event__title", "stripe_payment_intent_id"]
    readonly_fields = [
        "id", "reference", "attendee", "event",
        "total_amount", "currency",
        "idempotency_key", "stripe_payment_intent_id",
        "expires_at", "confirmed_at", "cancelled_at",
        "created_at", "updated_at",
        "status",   # use actions to change status — never direct edit
    ]
    inlines  = [OrderItemInline]
    actions  = ["soft_delete_orders", "refund_selected_orders"]

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .filter(is_deleted=False)
            .select_related("attendee", "event", "event__org")
            .annotate(_items_count=Count("items"))
        )

    @admin.display(description="Status")
    def status_badge(self, obj):
        from django.utils.html import format_html
        colours = {
            OrderStatus.PENDING:   "#e9c46a",
            OrderStatus.CONFIRMED: "#2a9d8f",
            OrderStatus.CANCELLED: "#e76f51",
            OrderStatus.REFUNDED:  "#457b9d",
        }
        colour = colours.get(obj.status, "#888")
        return format_html(
            '<span style="background:{};color:#fff;'
            'padding:2px 8px;border-radius:4px;">{}</span>',
            colour, obj.get_status_display(),
        )

    @admin.display(description="Items")
    def items_count(self, obj):
        return obj._items_count

    @admin.action(description="Soft-delete selected orders")
    def soft_delete_orders(self, request, queryset):
        count = queryset.update(is_deleted=True)
        self.message_user(request, f"{count} order(s) soft-deleted.")

    @admin.action(description="Refund selected orders (CONFIRMED only)")
    def refund_selected_orders(self, request, queryset):
        """
        Routes through services.refund_order() for every selected row so the
        real Stripe refund + inventory restoration happens — never a raw
        status flip. Rows that aren't CONFIRMED are skipped with a message.
        """
        refunded, skipped = 0, 0
        for order in queryset.filter(status=OrderStatus.CONFIRMED):
            try:
                services.refund_order(order=order, actor=request.user)
                refunded += 1
            except Exception as exc:
                skipped += 1
                self.message_user(request, f"Failed to refund {order.reference}: {exc}", level="ERROR")

        non_confirmed = queryset.exclude(status=OrderStatus.CONFIRMED).count()
        self.message_user(
            request,
            f"Refunded {refunded} order(s). "
            f"Skipped {non_confirmed} non-CONFIRMED order(s), {skipped} failure(s).",
        )


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display  = [
        "short_qr", "attendee_name", "attendee_email", "event", "tier",
        "status", "is_checked_in", "checked_in_at", "created_at",
    ]
    list_filter   = ["status", "event__org"]
    search_fields = ["qr_code", "attendee_name", "attendee_email", "event__title"]
    readonly_fields = [
        "id", "qr_code", "attendee", "event",
        "tier", "order_item", "status",
        "attendee_name", "attendee_email", "pdf_url",
        "checked_in_at", "created_at", "updated_at",
    ]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .filter(is_deleted=False)
            .select_related("attendee", "event", "tier", "order_item__order")
        )

    @admin.display(description="QR Code")
    def short_qr(self, obj):
        return obj.qr_code[:12] + "…"

    @admin.display(description="Checked In", boolean=True)
    def is_checked_in(self, obj):
        return obj.is_checked_in
