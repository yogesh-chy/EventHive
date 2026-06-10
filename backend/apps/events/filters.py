import django_filters

from .models import Event, EventStatus

class EventFilter(django_filters.FilterSet):

    status = django_filters.ChoiceFilter(choices=EventStatus.choices)
    city = django_filters.CharFilter(field_name="city", lookup_expr="icontains")
    country = django_filters.CharFilter(field_name="country", lookup_expr="iexact")
    start_after = django_filters.IsoDateTimeFilter(field_name="start_datetime", lookup_expr="gte", label="Events starting on or after this datetime(ISO 8601).")
    start_before = django_filters.IsoDateTimeFilter(field_name="start_datetime", lookup_expr="lte", label="Events starting on or before this datetime.")
    org_slug = django_filters.CharFilter(field_name="org__slug", lookup_expr="iexact", label="Filter by organization slug.")

    class Meta:
        model = Event
        fields = ["status", "city", "country", "org_slug", "start_after", "start_before"]