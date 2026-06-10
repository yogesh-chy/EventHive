"""
core/cache.py  ·  PHASE 2

Centralised cache helpers for EventHive.

All cache keys are namespaced under "eventhive:<domain>:<type>:<id>" to:
  - prevent collisions between apps sharing the same Redis instance
  - allow targeted pattern-delete per domain (e.g. wipe all event caches)

Predicted problems addressed:
──────────────────────────────
1.  delete_pattern() only exists on django-redis backends.
    LocMemCache (used in unit tests) raises AttributeError.
    → Wrapped in try/except; silently degrades to TTL-based expiry.

2.  Cache key collisions between event detail keys and Phase 3
    seat-lock keys → strict namespacing: "eventhive:event:*" vs
    "eventhive:seat:*" — never overlap.

3.  Cache stampede on popular events after TTL expiry (many concurrent
    requests all miss and all rebuild the cache simultaneously).
    → callers should use get_or_set() with a short lock (Phase 5).
      For now, TTL is staggered: detail=5 min, list/search=2 min.

4.  Stale list-cache entries after an event update:
    → invalidate_event_cache() tries pattern-delete on list/* and
      search/* keys; falls back to TTL on non-redis backends.

5.  Cache key from unsorted query params (e.g. ?city=ktm&status=PUBLISHED
    vs ?status=PUBLISHED&city=ktm should hit the same key):
    → event_list_key() sorts the dict before hashing.
"""

import hashlib
import json
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

# ── TTLs (seconds) ────────────────────────────────────────────────────────────
EVENT_DETAIL_TTL = 300   # 5 minutes — per blueprint spec
EVENT_LIST_TTL   = 120   # 2 minutes — short enough to self-heal
EVENT_SEARCH_TTL = 120   # 2 minutes


# ── Key builders ──────────────────────────────────────────────────────────────

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


# ── Invalidation ──────────────────────────────────────────────────────────────

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


# Backward compatibility aliases for old names used in views/signals
event_detail_keys = event_detail_key
invalidation_event_cache = invalidate_event_cache