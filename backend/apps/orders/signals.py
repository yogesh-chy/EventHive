import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from core.cache import invalidate_order_cache
from .models import Order

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Order, dispatch_uid="orders.invalidate_order_cache_on_save")
def invalidate_cache_on_order_save(sender, instance: Order, **kwargs):
    if not instance.reference:
        return  # not yet assigned — nothing meaningful to invalidate
    try:
        invalidate_order_cache(instance.reference)
    except Exception:
        logger.exception(
            "Failed to invalidate order cache. ref=%s — expires at TTL.",
            instance.reference,
        )