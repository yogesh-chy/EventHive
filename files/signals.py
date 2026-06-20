"""
apps/orders/signals.py  ·  PHASE 3  (re-aligned to blueprint — Payments)

CHANGE FROM PREVIOUS VERSION:
  Cache invalidation now keys on instance.reference, not instance.id —
  views.py and services.py both cache/invalidate order detail under
  order_detail_key(reference) since the public API is reference-addressed.
  Using the UUID id here would silently invalidate a key nobody ever reads
  from, leaving the real cached entry stale.

PREDICTED PROBLEMS ADDRESSED:
  1. Cache key mismatch between writer and invalidator → both now derive
     the key from the same field (reference).
  2. Signal firing before `reference` is assigned (e.g. mid-migration
     backfill calling .save() in a loop) → reference is generated inside
     services.create_order() before the first save, so by the time
     post_save fires, reference is always already populated. Guarded with
     a falsy check regardless, since defensive code costs nothing here.
  3. Signal failure crashing a legitimate save → bare try/except; failure
     logged but never propagated.
"""

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
