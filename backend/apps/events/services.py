import logging
import uuid as _uuid

from django.db import transaction
from django.utils.text import slugify

from .models import Event, EventStatus, TicketTier

logger = logging.getLogger(__name__)

MAX_SLUG_RETRIES = 100

# ---- Slug Generator ----
def generate_unique_slug(title: str) -> str:

    base_slug = slugify(title)
    if not base_slug:
        base_slug = f"event-{_uuid.uuid4().hex[:8]}"

    slug = base_slug
    for counter in range(1, MAX_SLUG_RETRIES + 1):
        if not Event.objects.filter(slug=slug).exists():
            return slug
        slug = f"{base_slug}-{counter}"
    
    return f"{base_slug}-{_uuid.uuid4().hex[:8]}"


# ---- Event Creation ---
def create_event(*, validated_data: dict, org, actor) -> Event:
    title = validated_data.get("title", "")
    validated_data["slug"] = generate_unique_slug(title)
    validated_data["org"] = org
    validated_data.setdefault("status", EventStatus.DRAFT)

    with transaction.atomic():
        event = Event.objects.create(**validated_data)
        logger.info("Event created: slug=%s org_id=%s actor=%s", event.slug, org.pk, actor.pk)
    return event


# ---- Event Update ----
def update_event(*, event: Event, validated_data: dict, actor) -> Event:
    validated_data.pop("slug", None)
    validated_data.pop("status", None)
    validated_data.pop("org", None)

    for attr, value in validated_data.items():
        setattr(event, attr, value)
    
    event.save()
    logger.info("Event update: slug=%s actor=%s fields=%s", event.slug, actor.pk, list(validated_data.keys()))
    return event


# ---- Status Transitions ----
def publish_event(*, event:Event, actor) -> Event:

    if not event.can_transition_to(EventStatus.PUBLISHED):
        raise ValueError(f"Cannot publish an event with status '{event.status}'.", f"valid transitions: {event.get_valid_transitions() or 'none'}.")
    
    from django.utils import timezone

    errors: list[str] = []

    if not event.ticket_tiers.filter(is_active=True).exists():
        errors.append("Event must have at least one active ticket tier before publishing.")
    
    
    if event.end_datetime <= timezone.now():
        errors.append("Cannot publish an event whose end_datetime is in past.")
    
    if errors:
        raise ValueError(" | ".join(errors))
    
    with transaction.atomic():
        event.status = EventStatus.PUBLISHED
        event.save(update_fields=["status", "updated_at"])
    
    logger.info("Event published: slug=%s actor=%s", event.slug, actor.pk)
    return event

def cancel_event(*, event: Event, actor) -> Event:

    if not event.can_transition_to(EventStatus.CANCELLED):
        raise ValueError(f"Cannot cancel an event with status '{event.status}'.")
    
    with transaction.atomic():
        event.status = EventStatus.CANCELLED
        event.save(update_fields=["status", "updated_at"])

    logger.info("Event cancelled: slug=%s actor=%s", event.slug, actor.pk)
    return event



# ---- Ticket Tier ----
def create_ticket_tier(*, event: Event, validated_data: dict, actor) -> TicketTier:
    _validate_tier_sale_window(validated_data, event)
    tier = TicketTier.objects.create(event=event, **validated_data)
    logger.info("TicketTier created: id=%s event=%s actor=%s", tier.pk, event.slug, actor.pk)
    return tier

def update_ticket_tier(*, tier: TicketTier, validated_data: dict, actor) -> TicketTier:
    _validate_tier_sale_window(validated_data, tier.event)
    for attr, value in validated_data.items():
        setattr(tier, attr, value)
    tier.save()
    logger.info("TicketTier updated: id=%s event=%s actor=%s", tier.pk, tier.event.slug, actor.pk)
    return tier

def _validate_tier_sale_window(data: dict, event: Event) -> None:
    sale_start = data.get("sale_start")
    sale_end = data.get("sale_end")

    if sale_start and sale_end and sale_start >= sale_end:
        raise ValueError("sale_start must be before sale_end.")
    
    if sale_end and sale_end > event.start_datetime:
        raise ValueError("sale_end cannot be after the event's start_datetime." "Ticket sales should close before the event begins.")