import hashlib
import json
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

# ---- TTLs (seconds) ----
EVENT_DETAIL_TTL = 300   # 5 minutes — per blueprint spec
EVENT_LIST_TTL   = 120   # 2 minutes — short enough to self-heal
EVENT_SEARCH_TTL = 120   # 2 minutes
SEAT_LOCK_TTL    = 600   # 10 min — Phase 3
ORDER_DETAIL_TTL = 60    # 1 min  — Phase 3


# ---- Key builders ----

def event_detail_key(slug: str) -> str:
    """eventhive:event:detail:<slug>"""
    return f"eventhive:event:detail:{slug}"


def event_list_key(query_params: dict) -> str:
    """
    Deterministic hash of sorted query params.
    eventhive:event:list:<md5_hash>
    """
    param_str = json.dumps(query_params, sort_keys=True, default=str)
    param_hash = hashlib.md5(param_str.encode(), usedforsecurity=False).hexdigest()
    return f"eventhive:event:list:{param_hash}"


def event_search_key(query: str, page: str | int = 1) -> str:
    """eventhive:event:search:<query_hash>:<page>"""
    q_hash = hashlib.md5(query.lower().encode(), usedforsecurity=False).hexdigest()
    return f"eventhive:event:search:{q_hash}:{page}"


def org_detail_key(org_id: str) -> str:
    """eventhive:org:detail:<org_id>"""
    return f"eventhive:org:detail:{org_id}"


# ---- Phase 3 keys ----

def seat_lock_key(tier_id: str, user_id: str) -> str:
    # eventhive:seat:lock:<tier_id>:<user_id>
    return f"eventhive:seat:lock:{tier_id}:{user_id}"


def order_detail_key(order_id: str) -> str:
    # eventhive:order:detail:<order_id>
    return f"eventhive:order:detail:{order_id}"


def acquire_seat_lock(tier_id: str, user_id: str, quantity: int) -> bool:
    # cache.add() only writes if the key does not already exist.
    # Redis backends implement this atomically with SET NX semantics.
    key      = seat_lock_key(str(tier_id), str(user_id))
    acquired = cache.add(key, str(quantity), SEAT_LOCK_TTL)
    logger.debug("seat_lock acquire key=%s acquired=%s", key, acquired)
    return bool(acquired)


def release_seat_lock(tier_id: str, user_id: str) -> None:
    cache.delete(seat_lock_key(str(tier_id), str(user_id)))


def get_seat_lock_quantity(tier_id: str, user_id: str) -> int | None:
    value = cache.get(seat_lock_key(str(tier_id), str(user_id)))
    return int(value) if value is not None else None


# ---- Invalidation ----
def invalidate_event_cache(slug: str) -> None:
    """
    Bust caches for a specific event and all list/search pages.

    Called:
      - After any Event.save() (via post_save signal)
      - After any TicketTier.save() (tier changes affect min_price / is_available)
    """
    # 1. Hard-delete the detail key immediately.
    detail_key = event_detail_key(slug)
    cache.delete(detail_key)
    logger.debug("cache.delete key=%s", detail_key)

    # 2. Pattern-delete list and search keys (django-redis only).
    try:
        n1 = cache.delete_pattern("eventhive:event:list:*")
        n2 = cache.delete_pattern("eventhive:event:search:*")
        logger.debug("cache.delete_pattern cleared list=%s search=%s keys", n1, n2)
    except AttributeError:
        # Non-redis backend (e.g. LocMemCache in tests) — list/search keys
        # will expire naturally at their TTL. This is acceptable.
        logger.debug(
            "Cache backend does not support delete_pattern. "
            "List/search caches will expire at TTL."
        )


def invalidate_org_cache(org_id: str) -> None:
    """Bust org detail cache. Called after Org.save()."""
    cache.delete(org_detail_key(str(org_id)))


def invalidate_order_cache(order_id: str) -> None:
    # Bust order detail cache. Called from service on every status transition.
    cache.delete(order_detail_key(str(order_id)))


# Backward compatibility aliases for old names used in views/signals
event_detail_keys = event_detail_key
invalidation_event_cache = invalidate_event_cache
