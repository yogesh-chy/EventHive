import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from services.realtime import seat_group_name


def _get_event_by_slug(slug: str):
    """Sync helper — fetches the Event row. Called via database_sync_to_async
    so it runs in a short-lived worker thread whose DB connection is closed
    immediately after this function returns."""
    from apps.events.models import Event
    return Event.objects.get(slug=slug, is_deleted=False)


class SeatConsumer(AsyncWebsocketConsumer):
    """
    One group per event (`seats_<slug>`). Clients connect to watch a single
    event's live seat count; apps.orders.services broadcasts to the group
    whenever that event's inventory actually changes.

    Written as an AsyncWebsocketConsumer (not the sync WebsocketConsumer) so
    that database_sync_to_async manages the ORM query in a short-lived thread
    whose DB connection is closed as soon as the query returns.  This prevents
    an AccessShareLock on `events_event` from persisting into the WebSocket
    lifecycle, which was deadlocking against TransactionTestCase teardown
    TRUNCATE statements (which need AccessExclusiveLock).
    """

    async def connect(self):
        self.slug = self.scope["url_route"]["kwargs"]["slug"]
        self.group_name = seat_group_name(self.slug)

        try:
            # database_sync_to_async runs _get_event_by_slug in a thread and
            # closes that thread's DB connection before returning — so no lock
            # persists into the rest of the WebSocket lifecycle.
            event = await database_sync_to_async(_get_event_by_slug)(self.slug)
        except Exception:
            # Close before accept(): the handshake never completes, so the
            # client sees a rejected connection rather than an open socket
            # that will never receive anything useful.
            await self.close(code=4404)
            return

        # Snapshot the seat count now; we won't touch the DB again from here.
        seats_remaining = event.seats_remaining

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Push the current count immediately on connect — a client that joins
        # between two purchases shouldn't have to wait for the next change.
        await self.send(text_data=json.dumps({"seats_remaining": seats_remaining}))

    async def disconnect(self, close_code):
        # group_name is only set if connect() reached group_add().
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def seat_update(self, event_msg):
        """Handler name must match the `type` key sent in group_send() calls
        — see services/realtime.py broadcast_seat_update()."""
        await self.send(text_data=json.dumps({"seats_remaining": event_msg["seats_remaining"]}))
