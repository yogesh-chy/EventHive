from django.contrib import admin
from django.db.models import Count

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
        "short_id", "attendee", "event", "status_badge",
        "total_amount", "currency", "items_count",
        "expires_at", "created_at",
    ]
    list_filter   = ["status", "currency", "event__org"]
    search_fields = ["id", "attendee__email", "event__title", "payment_intent_id"]
    readonly_fields = [
        "id", "attendee", "event",
        "total_amount", "currency", "payment_intent_id",
        "expires_at", "created_at", "updated_at",
        "status",   # use actions to change status — never direct edit
    ]
    inlines  = [OrderItemInline]
    actions  = ["soft_delete_orders"]

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)   # enforce soft-delete only
        return actions

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .filter(is_deleted=False)
            .select_related("attendee", "event", "event__org")
            .annotate(_items_count=Count("items"))
        )

    @admin.display(description="ID")
    def short_id(self, obj):
        return str(obj.id)[:8] + "…"

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


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display  = [
        "short_qr", "attendee", "event", "tier",
        "status", "checked_in_at", "created_at",
    ]
    list_filter   = ["status", "event__org"]
    search_fields = ["qr_code", "attendee__email", "event__title"]
    readonly_fields = [
        "id", "qr_code", "attendee", "event",
        "tier", "order_item", "status",
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
