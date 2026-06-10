
from django.contrib import admin
from django.utils.html import format_html

from .models import Event, EventStatus, TicketTier


class TicketTierInline(admin.TabularInline):
    model = TicketTier
    extra = 0
    fields = ["name", "price", "quantity", "quantity_sold", "is_active", "sale_start", "sale_end"]
    readonly_fields = ["quantity_sold"]
    show_change_link = True


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title","org","status_badge","city","start_datetime","total_capacity","tickets_sold","seats_remaining","created_at"]
    list_filter = ["status", "country", "org"]
    search_fields = ["title", "slug", "city", "description"]
    readonly_fields = ["id","slug","tickets_sold","search_vector","created_at","updated_at","created_by"]
    list_select_related = True
    prepopulated_fields = {}   # Slug is auto-generated — never prepopulated from admin.
    inlines = [TicketTierInline]
    actions = ["soft_delete_events"]

    # Disable the built-in delete action to enforce soft delete.
    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    fieldsets = (
        ("Core", {
            "fields": ("id", "title", "slug", "org", "status", "description"),
        }),
        ("Location & Dates", {
            "fields": ("venue", "city", "country", "start_datetime", "end_datetime"),
        }),
        ("Capacity", {
            "fields": ("total_capacity", "tickets_sold"),
        }),
        ("Media", {
            "fields": ("banner",),
        }),
        ("Metadata", {
            "fields": ("created_at", "updated_at", "created_by", "is_deleted"),
            "classes": ("collapse",),
        }),
    )

    def get_queryset(self, request):
        return (super().get_queryset(request).filter(is_deleted=False).select_related("org").prefetch_related("ticket_tiers"))

    @admin.display(description="Status")
    def status_badge(self, obj):
        colours = {EventStatus.DRAFT: "#888",EventStatus.PUBLISHED: "#2a9d8f",EventStatus.CANCELLED: "#e76f51",EventStatus.COMPLETED: "#264653",}
        colour = colours.get(obj.status, "#888")
        return format_html('<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;">{}</span>', colour, obj.get_status_display(),)

    @admin.display(description="Seats remaining")
    def seats_remaining(self, obj):
        return obj.seats_remaining

    @admin.action(description="Soft-delete selected events")
    def soft_delete_events(self, request, queryset):
        count = queryset.update(is_deleted=True)
        self.message_user(request, f"{count} event(s) soft-deleted.")


@admin.register(TicketTier)
class TicketTierAdmin(admin.ModelAdmin):
    list_display = ["name", "event", "price", "quantity", "quantity_sold", "available_quantity", "is_active", "sale_start", "sale_end"]
    list_filter = ["is_active", "event__status"]
    search_fields = ["name", "event__title"]
    readonly_fields = ["id", "quantity_sold", "created_at", "updated_at"]
    list_select_related = True

    def get_queryset(self, request):
        return (super().get_queryset(request).filter(is_deleted=False).select_related("event", "event__org")
        )

    @admin.display(description="Available")
    def available_quantity(self, obj):
        return obj.available_quantity