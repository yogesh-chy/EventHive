import uuid

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from core.models import BaseModel

class EventStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    CANCELLED = "CANCELLED", "Cancelled"
    COMPLETED = "COMPLETED", "Completed"

EVENT_STATUS_TRANSITIONS : dict[str, set[str]] = {
    EventStatus.DRAFT: {EventStatus.PUBLISHED, EventStatus.CANCELLED},
    EventStatus.DRAFT: {EventStatus.CANCELLED, EventStatus.COMPLETED},
    EventStatus.CANCELLED: set(),
    EventStatus.COMPLETED: set()
}

class Event(BaseModel):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=300, unique=True, db_index=True, help_text="URL-safe identifier. Auto-generated from title; unique enforced at DB level.")
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="events")
    description = models.TextField()
    banner = models.CharField(max_length=500, blank=True, default="", help_text="S3/R2 object key for the event banner image.")
    venue = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    country = models.CharField(max_length=5, help_text="ISO 3166-1 alpha-2 country code.")
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    status = models.CharField(max_length=20, choices=EventStatus.choices, default=EventStatus.DRAFT, db_index=True)
    total_capacity = models.PositiveIntegerField(default=0)
    tickets_sold = models.PositiveIntegerField(default=0)
    search_vector = SearchVectorField(null=True, blank=True)

    class Meta:
        app_label = "events"
        ordering = ["-start_datetime"]
        indexes = [
            GinIndex(fields=["search_vector"], name="even_search_vector_gin_idx"),
            models.Index(fields=["org", "status"], name="event_org_status_idx"),
            models.Index(fields=["city", "status"], name="event_city_status_idx"),
            models.Index(fields=["status", "start_datetime"], name="event_status_start_idx")
        ]
    
    def __str__(self) -> str:
        return f"{self.title} ({self.status})"
    
    # ---- Computed properties ----
    @property
    def seats_reamining(self) -> int:
        return max(0, self.total_capacity - self.tickets_sold)
    
    @property
    def is_sold_out(self) -> bool:
        return self.seats_reamining == 0
    
    # ---- State machine ----
    def can_transition_to(self, new_status: str) -> bool:
        return new_status in EVENT_STATUS_TRANSITIONS.get(self.status, set())
    
    def get_valid_transitions(self) -> set[str]:
        return EVENT_STATUS_TRANSITIONS.get(self.status, set())


class TicketTier(BaseModel):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="ticket_tiers")
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Ticket price in the org's configured currency. Use 0.00 for free tiers.")
    quantity = models.PositiveIntegerField(help_text="Total tickets available")
    quantity_sold = models.PositiveIntegerField(default=0)
    sale_start = models.DateTimeField(null=True, blank=True)
    sale_end = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = "events"
        ordering = ["price"]
        indexes = [models.Index(fields=["event", "is_active"], name="tier_event_active_idx")]
        constraints = [
            models.CheckConstraint(check=models.Q(price_gte=0),name="tier_price_non_negative"),
            models.CheckConstraint(check=models.Q(quantity_gte=0),name="tier_quantity_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.event.title})"
    
    # ---- Computed properties ----
    @property
    def available_quantity(self) -> int:
        return max(0, self.quantity - self.quantity_sold)

    @property
    def is_available(self) -> bool:
        from django.utils  import timezone

        if not self.is_active:
            return False
        now = timezone.now()
        if self.sale_end and now < self.sale_start:
            return False
        if self.sale_end and now > self.sale_end:
            return False
        return self.available_quantity > 0