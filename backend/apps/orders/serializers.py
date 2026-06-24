from rest_framework import serializers

from .models import Order, OrderItem, Ticket


# ── Read serializers ───────────────────────────────────────────────────────────

class TicketSerializer(serializers.ModelSerializer):
    tier_name     = serializers.CharField(source="tier.name",  read_only=True)
    event_name    = serializers.CharField(source="event.title", read_only=True)
    is_checked_in = serializers.BooleanField(read_only=True)
    pdf_url       = serializers.SerializerMethodField()

    class Meta:
        model  = Ticket
        fields = [
            "id", "qr_code", "status", "is_checked_in",
            "tier_name", "event_name",
            "attendee_name", "attendee_email", "pdf_url",
            "checked_in_at", "created_at",
        ]
        read_only_fields = fields
    
    def get_pdf_url(self, obj):
        """
        Phase 4: Ticket.pdf_url stores an S3/R2 *object key* (per its own
        field docstring), not a usable URL -- serializing it as-is would
        hand the API consumer an internal storage path instead of a working
        link, and would leak that path even though it's not meant to be
        public. This generates a fresh, time-limited presigned URL on every
        read instead. Returns None until the async asset-generation task
        (tasks.tickets.generate_ticket_assets_task) has completed.
        """
        if not obj.pdf_url:
            return None
        from django.conf import settings

        from services.storage import generate_presigned_url

        return generate_presigned_url(key=obj.pdf_url, expires_in=settings.TICKET_PDF_LINK_TTL_SECONDS)


class OrderItemSerializer(serializers.ModelSerializer):
    tier_id    = serializers.UUIDField(source="tier.id",   read_only=True)
    tier_name  = serializers.CharField(source="tier.name", read_only=True)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    subtotal   = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    tickets    = TicketSerializer(many=True, read_only=True)

    class Meta:
        model  = OrderItem
        fields = ["id", "tier_id", "tier_name", "quantity", "unit_price", "subtotal", "tickets"]
        read_only_fields = fields


class OrderListSerializer(serializers.ModelSerializer):
    """Lightweight — no nested items. Used for paginated list."""
    event_title  = serializers.CharField(source="event.title", read_only=True)
    event_slug   = serializers.CharField(source="event.slug",  read_only=True)
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model  = Order
        fields = [
            "reference", "event_title", "event_slug",
            "status", "total_amount", "currency",
            "expires_at", "created_at",
        ]
        read_only_fields = fields


class OrderDetailSerializer(serializers.ModelSerializer):
    """Full detail: items, tickets, payment + refund timestamps."""
    id              = serializers.UUIDField(read_only=True)
    event_title     = serializers.CharField(source="event.title", read_only=True)
    event_slug      = serializers.CharField(source="event.slug",  read_only=True)
    attendee_email  = serializers.EmailField(source="attendee.email", read_only=True)
    total_amount    = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    items           = OrderItemSerializer(many=True, read_only=True)
    is_expired      = serializers.BooleanField(read_only=True)

    class Meta:
        model  = Order
        fields = [
            "reference", "id",
            "event_title", "event_slug",
            "attendee_email",
            "status", "is_expired",
            "total_amount", "currency",
            "stripe_payment_intent_id",
            "items",
            "expires_at", "confirmed_at", "cancelled_at",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


# ── Write serializers ──────────────────────────────────────────────────────────

class CheckoutItemSerializer(serializers.Serializer):
    tier_id  = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, max_value=20)


class OrderCreateSerializer(serializers.Serializer):
    """Input for POST /api/v1/orders/. Creation delegated to services.create_order()."""
    event_slug = serializers.SlugField()
    items      = CheckoutItemSerializer(many=True)

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("Order must contain at least one item.")
        tier_ids = [str(i["tier_id"]) for i in items]
        if len(tier_ids) != len(set(tier_ids)):
            raise serializers.ValidationError(
                "Duplicate tier_id detected. Combine quantities into a single item per tier."
            )
        return items

    def validate(self, attrs):
        from apps.events.models import Event, EventStatus
        from rest_framework.exceptions import NotFound, ValidationError

        try:
            event = Event.objects.select_related("org").get(
                slug=attrs["event_slug"], is_deleted=False,
            )
        except Event.DoesNotExist:
            raise NotFound(f"Event '{attrs['event_slug']}' not found.")

        if event.status != EventStatus.PUBLISHED:
            raise ValidationError(
                {"event_slug": "Tickets can only be purchased for published events."}
            )

        attrs["event"] = event
        return attrs
