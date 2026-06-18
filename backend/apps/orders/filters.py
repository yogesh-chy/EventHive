import django_filters
from .models import Order, OrderStatus

class OrderFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=OrderStatus.choices)
    event_slug = django_filters.CharFilter(field_name="event__slug", lookup_expr="iexact", label="Filter by event slug.")
    created_after = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte", label="Order created on or after this datetime(ISO 8601).")
    created_before = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte", label="Order created on or before this datetime (ISO 8601).")

    class Meta:
        model = Order
        fields = ["status", "event_slug", "created_after", "created_before"]