from decimal import Decimal
from rest_framework import serializers

from .models import Order, OrderItem, OrderStatus, Ticket, TicketStatus


# ---- Read Serializers ----
class TicketSerializer(serializers.ModelSerializer):
    tier_name = serializers.CharField(source="tier.name", read_only=True)
    event_name = serializers.CharField(source="event.title", read_only=True)

    class Meta:
        model = Ticket
        fields = ["id", "qr_code", "status", "tier_name", "event_name", "checked_in_at", "created_at"]
        read_only_fields = fields
    

class OrderItemSerializer(serializers.ModelSerializer):
    tier_id = serializers.UUIDField(source="tier.id", read_only=True)
    tier_name = serializers.CharField(source="tier.name", read_only=True)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    tickets = TicketSerializer(many=True, read_only=True)

    class Meta:
        model = OrderItem
        fields = ["id", "tier_id", "tier_name", "quantity", "unit_price", "subtotal", "tickets"]
        read_only_fields = fields


class OrderListSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source="event.title", read_only=True)
    event_slug = serializers.CharField(source="event.slug", read_only=True)

    class Meta:
        model = Order
        fields = ["id", "event_title", "event_slug", "status", "total_amount", "currency", "expires_at", "created_at"]
        read_only_fields = fields


class OrderDetailSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source="event.title", read_only=True)
    event_slug = serializers.CharField(source="event.slug", read_only=True)
    attendee_email = serializers.EmailField(source="attendee.email", read_only=True)
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Order
        fields = ["id", "event_title", "event_slug", "attendee_email", "status", "is_expired", "total_amount", "currency", "payment_intent_id", "items", "expires_at", "created_at", "updated_at"]
        read_only_fields = fields


# ---- Write Serializers ----
class CheckoutItemSerializer(serializers.Serializer):
    tier_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, max_value=20)


class OrderCreateSerializer(serializers.Serializer):
    event_slug = serializers.SlugField()
    items = CheckoutItemSerializer(many=True)

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("Order must contain at least one item.")
        tier_ids = [str(i["tier_id"]) for i in items]
        if len(tier_ids) != len(set(tier_ids)):
            raise serializers.ValidationError("Duplicate tier_id detected. Combine quantities into a single item per tier.")
        return items

    def validate(self, attrs):
        from apps.events.models import Event, EventStatus
        from rest_framework.exceptions import NotFound, ValidationError

        try:
            event = Event.objects.select_related("org").get(slug=attrs["event_slug"], is_deleted=False)
        except Event.DoesNotExist:
            raise NotFound(f"Event '{attrs['event_slug']}' not found.")
        
        if event.status != EventStatus.PUBLISHED:
            raise ValidationError({"event_slug": "Ticket can only be purchased for published events."})
        
        attrs["event"] = event
        return attrs