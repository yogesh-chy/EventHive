from django.urls import path

from .views import EventViewSet, TicketTierViewSet

# ---- Event Actions ----
event_list = EventViewSet.as_view({"get": "list", "post": "create"})
event_search = EventViewSet.as_view({"get": "search"})
event_detail = EventViewSet.as_view({"get": "retrieve", "patch": "partial_update"})
event_publish = EventViewSet.as_view({"post": "publish"})
event_cancel = EventViewSet.as_view({"post": "cancel"})

# ---- Tier Actions ----
tier_list = TicketTierViewSet.as_view({"get": "list", "post": "create"})
tier_detail = TicketTierViewSet.as_view({"get": "retrieve", "patch": "partial_update"})

urlpatterns = [
    # --- Events ---
    path("", event_list, name="event_list"),
    path("search/", event_search, name="event_search"),
    path("<slug:slug>/", event_detail, name="event_detail"),
    path("<slug:slug>/publish/", event_publish, name="event_publish"),
    path("<slug:slug>/cancel/", event_cancel, name="event_cancel"),

    # --- Ticket Tiers ---
    path("<slug:event_slug>/tiers/", tier_list, name="tier_list"),
    path("<slug:event_slug>/tiers/<uuid:id>/", tier_detail, name="tier_detail"),
]
