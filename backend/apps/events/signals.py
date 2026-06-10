import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from core.cache import invalidation_event_cache
from .models import Event, TicketTier

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Event, dispatch_uid="event.invalidate_event_cache_on_save")
def invalidate_cache_on_event_save(sender, instance: Event, **kwargs):

    try: 
        invalidation_event_cache(instance.slug)
    except Exception:
        logger.exception(
            "Failed to invalidate event cache after save. "
            "event_slug=%s - cache will expire at TTL.", instance.slug
        )


@receiver(post_save, sender=TicketTier, dispatch_uid="events.invalidate_event_cache_on_tier_save")
def invalidate_cache_on_tier_save(sender, instance: TicketTier, **kwargs):

    try:
        event = (
            instance.event
            if hasattr(instance, "_event_cache")
            else Event.objects.only("slug").get(pk=instance.event_id)
        )
        invalidation_event_cache(event.slug)
    except Exception:
        logger.exception(
            "Failed to invalidate event cache after tier save. "
            "tier_id=%s - cache will expire at TTL.", instance.pk
        )