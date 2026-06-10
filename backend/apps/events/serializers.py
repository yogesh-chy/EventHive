from decimal import Decimal
from rest_framework import serializers

from apps.events.models import Event, EventStatus, TicketTier


# ---- TicketTier ----
class TicketTierSerializer(serializers.ModelSerializer):
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.00"))
    available_quantity = serializers.IntegerField(read_only=True)
    is_available = serializers.BooleanField(read_only=True)

    class Meta:
        model = TicketTier
        fields = ["id", "name", "price", "quantity", "quantity_sold", "available_quantity", "sale_start", "sale_end", "is_active", "is_available", "created_at"]
        read_only_fields = ["id", "quantity_sold", "available_quantity", "is_available", "created_at"]

    def validate(self, attrs):
        sale_start = attrs.get("sale_start")
        sale_end = attrs.get("sale_end")

        if sale_start and sale_end and sale_start >= sale_end:
            raise serializers.ValidationError({"sale_end":"sale_end must be after sale_start."})
        return attrs

class TicketTierSummarySerializer(serializers.ModelSerializer):
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    available_quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = TicketTier
        fields = ["id", "name", "price", "available_quantity", "is_active", "sale_start", "sale_end"]


# ---- Event ----
class EventListSerializer(serializers.ModelSerializer):
    org_name = serializers.CharField(source="org.name", read_only=True)
    seats_remaining = serializers.IntegerField(read_only=True)
    is_sold_out = serializers.BooleanField(read_only=True)
    min_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True, allow_null=True)

    class Meta:
        model = Event
        fields = ["id", "title", "slug", "org_name", "banner", "venue", "city", "country", "start_datetime", "end_datetime", "status", "total_capacity", "seats_remaining", "is_sold_out", "min_price"]

        # banner - # TODO Phase 4: return pre-signed S3 URL, not raw key

class EventDetailSerializer(serializers.ModelSerializer):
    org_name = serializers.CharField(source="org.name", read_only=True)
    org_id = serializers.UUIDField(source="org.id", read_only=True)
    seats_remaining = serializers.IntegerField(read_only=True)
    is_sold_out = serializers.BooleanField(read_only=True)
    ticket_tiers = TicketTierSummarySerializer(many=True, read_only=True)

    class Meta:
        model = Event
        fields = ["id", "title", "slug", "org_id", "org_name", "description", "banner", "venue", "city", "country", "start_datetime", "end_datetime", "status", "total_capacity", "tickets_sold", "seats_remaining", "is_sold_out", "ticket_tiers", "created_at", "updated_at"]

        # banner - # TODO Phase 4: pre-signed URL

class EventCreateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Event
        fields = ["title", "description", "banner", "venue", "city", "country", "start_datetime", "end_datetime", "total_capacity",]
    
    def validate(self, attrs):
        start = attrs.get("start_datetime")
        end = attrs.get("end_datetime")
        if start and end and end <= start:
            raise serializers.ValidationError({"end_datetime":"end_datetime must be after start_datetime."})
        return attrs
    
    def validate_total_capacity(self, value):
        if value < 0:
            raise serializers.ValidationError("total_capacity must be 0 or greater.")
        return value

class EventUpdateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Event
        fields = ["title", "description", "banner", "venue", "city", "country", "start_datetime", "end_datetime", "total_capacity",]

    
    def validate_total_capacity(self, value):
        instance = self.instance
        if instance and value < instance.tickets_sold:
            raise serializers.ValidationError(
                f"Cannot set total_capacity to {value};"
                f"{instance.ticket_sold} tickets are already sold."
            )
        return value

    def validate(self, attrs):
        instance = self.instance
        start = attrs.get("start_datetime", getattr(instance, "start_datetime", None))
        end = attrs.get("end_datetime", getattr(instance, "end_datetime", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"end_datetime":"end_datetime must be after start_datetime."})
        return attrs


class EventSearchSerializer(serializers.ModelSerializer):
    rank = serializers.FloatField(read_only=True)
    seats_remaining = serializers.IntegerField(read_only=True)

    class Meta:
        model = Event
        fields = ["id", "title", "slug", "city", "country", "start_datetime", "status", "seats_remaining", "rank"]