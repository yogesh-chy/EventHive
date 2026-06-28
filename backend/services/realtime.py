import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

def seat_group_name(event_slug: str) -> str:
    return f"seats_{event_slug}"

def broadcast_seat_update(event_slug: str, seats_remaining: int) -> None:

    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            # CHANNEL_LAYERS not configured (e.g. a settings override in
            # some environment) -- nothing to broadcast to.
            return
        async_to_sync(channel_layer.group_send)(
            seat_group_name(event_slug),
            {"type": "seat_update", "seats_remaining": seats_remaining}
        )
    except Exception:
        logger.exception("Failed to broadcast seat update for event=%s", event_slug)