import logging

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.core.cache import cache
from django.db.models import DecimalField, OuterRef, Prefetch, Subquery
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core.cache import EVENT_DETAIL_TTL, EVENT_LIST_TTL, event_detail_keys, event_list_key, event_search_key, invalidation_event_cache
from core.pagination import EventCursorPagination
from core.mixins import AuditLogMixin, OrgScopedMixin
from core.permissions import IsOrganizer, IsEventOrganizer

from . import services
from .filters import EventFilter
from .models import Event, EventStatus, TicketTier
from .serializers import EventCreateSerializer, EventDetailSerializer, EventListSerializer, EventSearchSerializer, EventUpdateSerializer, TicketTierSerializer


logger = logging.getLogger(__name__)


# ---- Helper ----
def _base_event_queryset():
    min_price_sq = (
        TicketTier.objects.filter(
            event=OuterRef("pk"),
            is_active=True,
            is_deleted=False
        )
        .order_by("price")
        .values("price")[:1]
    )
    return (
        Event.objects.filter(is_deleted=False)
        .select_related("org")
        .prefetch_related(
            Prefetch("ticket_tiers", queryset=TicketTier.objects.filter(is_deleted=False).order_by("price"))
        )
        .annotate(min_price=Subquery(min_price_sq, output_field=DecimalField()))
    )


# ---- EventViewSet ----

class EventViewSet(OrgScopedMixin, AuditLogMixin, viewsets.GenericViewSet):
    lookup_field = "slug"
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = EventFilter
    ordering_fields = ["start_datetime", "created_at", "title"]
    ordering = ["-start_datetime"]
    pagination_class = EventCursorPagination
    audit_action = "EVENT"

    def get_permissions(self):
        if self.action in ("list", "retrieve", "search"):
            return [AllowAny()]

        if self.action in ("create",):
            return [IsAuthenticated(), IsOrganizer()]
        
        if self.action in ("partial_update", "publish", "cancel"):
            return [IsAuthenticated(), IsEventOrganizer()]
        
        return [IsAuthenticated()]
    
    def get_queryset(self):
        qs = _base_event_queryset()

        if self.action in ("list", "retrieve", "search"):
            qs = qs.filter(status=EventStatus.PUBLISHED)
        elif self.action in ("partial_update", "publish", "cancel"):
            qs = self.apply_org_scope(qs)
        elif self.action == "create":
            qs = self.apply_org_scope(qs)

        return qs
    
    def get_serializer_class(self):
        if self.action == "list":
            return EventListSerializer

        if self.action == "retrieve":
            return EventDetailSerializer
        
        if self.action == "create":
            return EventCreateSerializer
        
        if self.action == "partial_update":
            return EventUpdateSerializer
        
        if self.action == "search":
            return EventSearchSerializer
        
        return EventDetailSerializer

    # ---- Public: List ----
    def list(self, request):
        cache_key = event_list_key(dict(request.query_params))
        cached = cache.get(cache_key)

        if cached is not None:
            return Response(cached)
        
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response_data = self.get_paginated_response(serializer.data).data
        else:
            serializer = self.get_serializer(queryset, many=True)
            response_data = serializer.data

        cache.set(cache_key, response_data, EVENT_LIST_TTL)
        return Response(response_data)

    # ---- Public: Retrieve ----
    def retrieve(self, request, slug=None):
        cache_key = event_detail_keys(slug)
        cached = cache.get(cache_key)

        if cached is not None:
            return Response(cached)

        event = self.get_object()
        serializer = self.get_serializer(event)
        cache.set(cache_key, serializer.data, EVENT_DETAIL_TTL)
        return Response(serializer.data)
    
    # ---- Public: Search ----
    @action(detail=False, methods=["get"], url_name='search')
    def search(self, request):
        query_str = request.query_params.get("q", "").strip()

        if not query_str:
            return Response({"detail": "Query parameter 'q' is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        page_num = request.query_params.get("page", "1")
        cache_key = event_search_key(query_str, page_num)
        cached = cache.get(cache_key)

        if cached is not None:
            return Response(cached)
        
        search_query = SearchQuery(query_str, config="english")
        queryset = (
            _base_event_queryset()
            .filter(status=EventStatus.PUBLISHED, search_vector=search_query)
            .annotate(rank=SearchRank("search_vector", search_query))
            .order_by("-rank")
        )

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = EventSearchSerializer(page, many=True)
            response_data = self.get_paginated_response(serializer.data).data
        else:
            serializer = EventSearchSerializer(queryset, many=True)
            response_data = serializer.data

        cache.set(cache_key, response_data, EVENT_LIST_TTL)
        return Response(response_data)
    
    # ---- Organizer: Create ----
    def create(self, request):
        serializer = EventCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        org = self._resolve_org_from_request(request)

        try:
            event = services.create_event(validated_data=serializer.validated_data, org=org, actor=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        invalidation_event_cache(event.slug)
        return Response(EventDetailSerializer(event).data, status=status.HTTP_201_CREATED)

    # ---- Organizer: Partial Update ----
    def partial_update(self, request, slug=None):
        event = self.get_object()
        serializer = EventUpdateSerializer(event, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        try:
            updated_event = services.update_event(event=event, validated_data=serializer.validated_data, actor=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        
        invalidation_event_cache(updated_event.slug)
        return Response(EventDetailSerializer(updated_event).data)
    
    # ---- Organizer: Publish -----
    @action(detail=True, methods=["post"], url_path="publish")
    def publish(self, request, slug=None):
        event = self.get_object()

        try:
            updated = services.publish_event(event=event, actor=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        
        invalidation_event_cache(updated.slug)
        return Response(EventDetailSerializer(updated).data)
    
    # ---- Organizer: Cancel -----
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, slug=None):
        event = self.get_object()

        try:
            updated = services.cancel_event(event=event, actor=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        
        invalidation_event_cache(updated.slug)
        return Response(EventDetailSerializer(updated).data)
    
    # ---- Internal Helper ----
    def _resolve_org_from_request(self, request):
        from apps.organizations.models import Organization
        from rest_framework.exceptions import ValidationError

        org_id = request.data.get("org_id")
        user_org_ids = list(request.user.membership_set.filter(org__is_active=True).values_list("org_id", flat=True))

        if not user_org_ids:
            raise ValidationError("You are not a member of an active organization.")
        
        if org_id:
            if str(org_id) not in [str(i) for i in user_org_ids]:
                raise ValidationError("You are not a member of the specified organization.")
            return Organization.objects.get(pk=org_id)
        
        if len(user_org_ids) > 1:
            raise ValidationError("You belong to multiple organizations. Specify 'org_id' in the request body.")
        
        return Organization.objects.get(pk=user_org_ids[0])
    


# ---- TicketTierViewSet ----

class TicketTierViewSet(viewsets.GenericViewSet):
    serializer_class = TicketTierSerializer
    lookup_field = "id"

    def get_permissions(self):
        if self.action == "list":
            return [AllowAny()]
        return [IsAuthenticated(), IsEventOrganizer()]
    
    def _get_event(self):
        if hasattr(self, "_event"):
            return self._event
        
        slug = self.kwargs["event_slug"]
        qs = Event.objects.filter(is_deleted=False).select_related("org")

        if self.action != "list":
            user = self.request.user
            if getattr(user, 'role', None) != "ADMIN":
                org_ids = user.membership_set.filter(org__is_active=True).values_list("org_id", flat=True)
                qs = qs.filter(org_id__in=org_ids)
        
        try:
            self._event = qs.get(slug=slug)
        except Event.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound(f"Event '{slug}' not found.")
        
        return self._event
    
    def get_queryset(self):
        event = self._get_event()
        return TicketTier.objects.filter(event=event, is_deleted=False).order_by("price")
    
    # ---- List ----
    def list(self, request, event_slug=None):
        tiers = self.get_queryset()
        serializer = TicketTierSerializer(tiers, many=True)
        return Response(serializer.data)
    
    # ---- Create ---
    def create(self, request, event_slug=None):
        event = self._get_event()

        if event.status == EventStatus.CANCELLED:
            return Response({"detail": "Cannot add tiers to a cancelled event."}, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = TicketTierSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            tier = services.create_ticket_tier(event=event, validated_data=serializer.validated_data, actor=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        
        invalidation_event_cache(event.slug)
        return Response(TicketTierSerializer(tier).data, status=status.HTTP_201_CREATED)
    
    # ---- Retrieve ----
    def retrieve(self, request, event_slug=None, id=None):
        tier = self.get_queryset().get(pk=id)
        return Response(TicketTierSerializer(tier).data)
    
    # ---- Partial_Update ----
    def partial_update(self, request, event_slug=None, id=None):
        event = self._get_event()

        try:
            tier = self.get_queryset().get(pk=id)
        except TicketTier.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound("Ticket tier not found.")
        
        serializer = TicketTierSerializer(tier, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        try:
            updated = services.update_ticket_tier(tier=tier, validated_data=serializer.validated_data, actor=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        
        invalidation_event_cache(event.slug)
        return Response(TicketTierSerializer(updated).data)
