"""
apps/orders/filters.py  ·  PHASE 3

FilterSet for GET /api/v1/orders/.

PREDICTED PROBLEMS ADDRESSED:
  1. Filtering by invalid status value crashes ORM → ChoiceFilter with
     explicit choices rejects unknown values with a 400 response.
  2. Naive datetime values on date-range filters → IsoDateTimeFilter uses
     ISO 8601; Django converts to timezone-aware when USE_TZ=True.
  3. Attendee broadening scope via attendee_id filter (data leak) →
     attendee filter intentionally excluded. The queryset is already scoped
     to request.user by AttendeeOrderMixin before filters are applied.
  4. Admin support use-case (filter any user's orders by event) →
     AttendeeOrderMixin returns the full queryset for ADMIN role, so
     event_slug filter works across all users for admins.
"""

import django_filters
from .models import Order, OrderStatus


class OrderFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=OrderStatus.choices)

    event_slug = django_filters.CharFilter(
        field_name="event__slug",
        lookup_expr="iexact",
        label="Filter by event slug.",
    )
    created_after = django_filters.IsoDateTimeFilter(
        field_name="created_at",
        lookup_expr="gte",
        label="Orders created on or after this datetime (ISO 8601).",
    )
    created_before = django_filters.IsoDateTimeFilter(
        field_name="created_at",
        lookup_expr="lte",
        label="Orders created on or before this datetime.",
    )

    class Meta:
        model  = Order
        fields = ["status", "event_slug", "created_after", "created_before"]
