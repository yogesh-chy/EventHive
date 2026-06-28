"""
Phase 5: SeatConsumer (websockets/consumers.py), services/realtime.py's
broadcast, and its wiring into create_order/cancel_order/refund_order.

Uses channels.layers.InMemoryChannelLayer for these tests instead of the
real Redis-backed channel layer configured in settings -- it's Channels'
own recommended layer for tests: no external broker, fully isolated per
test, zero risk of one test's leftover group state leaking into another.

@pytest.mark.django_db(transaction=True) is required, not the default
@pytest.mark.django_db: SeatConsumer (a sync WebsocketConsumer) runs its
connect()/receive() methods in a worker thread via Channels' own
sync-to-async machinery, on a DB connection separate from the test's main
thread. The default django_db wraps a test in an uncommitted transaction
visible only to the connection that opened it -- a row created on the main
thread would be invisible to the consumer's thread without `transaction=True`
actually committing it.
"""
import json

import pytest
from asgiref.sync import async_to_sync
from channels.layers import InMemoryChannelLayer
from channels.testing import WebsocketCommunicator

from config.asgi import application
from tests.factories import EventFactory, OrderFactory, OrderItemFactory, TicketTierFactory, UserFactory


@pytest.fixture
def in_memory_channel_layer(settings):
    """Swap the real Redis-backed channel layer for the in-process one,
    for the duration of each test using this fixture."""
    settings.CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    }
    yield


def run_async(coro_func, *args, **kwargs):
    """Drives an async test body from a plain sync test function, so
    these tests don't require pytest-asyncio or any pytest.ini change."""
    return async_to_sync(coro_func)(*args, **kwargs)


@pytest.mark.django_db(transaction=True)
class TestSeatConsumerConnect:
    def test_connects_and_receives_initial_seat_count(self, in_memory_channel_layer):
        event = EventFactory(total_capacity=100, tickets_sold=40)

        async def scenario():
            communicator = WebsocketCommunicator(application, f"/ws/events/{event.slug}/seats/")
            connected, _ = await communicator.connect()
            assert connected

            message = await communicator.receive_from()
            payload = json.loads(message)
            assert payload == {"seats_remaining": 60}

            await communicator.disconnect()

        run_async(scenario)

    def test_rejects_connection_for_unknown_slug(self, in_memory_channel_layer):
        async def scenario():
            communicator = WebsocketCommunicator(application, "/ws/events/does-not-exist/seats/")
            connected, subprotocol_or_code = await communicator.connect()
            assert connected is False

        run_async(scenario)


@pytest.mark.django_db(transaction=True)
class TestSeatConsumerBroadcast:
    def test_receives_update_after_broadcast_seat_update(self, in_memory_channel_layer):
        from services.realtime import broadcast_seat_update

        event = EventFactory(total_capacity=50, tickets_sold=10)

        async def scenario():
            communicator = WebsocketCommunicator(application, f"/ws/events/{event.slug}/seats/")
            await communicator.connect()
            await communicator.receive_from()  # the initial count on connect

            await async_to_sync_broadcast(event.slug, 35)

            message = await communicator.receive_from()
            assert json.loads(message) == {"seats_remaining": 35}

            await communicator.disconnect()

        async def async_to_sync_broadcast(slug, remaining):
            # broadcast_seat_update is itself sync (uses async_to_sync
            # internally) -- call it via database_sync_to_async-equivalent
            # so it runs correctly from within this async test body.
            from asgiref.sync import sync_to_async

            await sync_to_async(broadcast_seat_update)(slug, remaining)

        run_async(scenario)

    def test_two_clients_on_different_events_are_isolated(self, in_memory_channel_layer):
        """A broadcast for event A must never reach a client watching
        event B -- group names are per-event by design."""
        from asgiref.sync import sync_to_async

        from services.realtime import broadcast_seat_update

        event_a = EventFactory(total_capacity=10, tickets_sold=0)
        event_b = EventFactory(total_capacity=10, tickets_sold=0)

        async def scenario():
            comm_a = WebsocketCommunicator(application, f"/ws/events/{event_a.slug}/seats/")
            comm_b = WebsocketCommunicator(application, f"/ws/events/{event_b.slug}/seats/")
            await comm_a.connect()
            await comm_b.connect()
            await comm_a.receive_from()
            await comm_b.receive_from()

            await sync_to_async(broadcast_seat_update)(event_a.slug, 5)

            msg_a = await comm_a.receive_from()
            assert json.loads(msg_a) == {"seats_remaining": 5}
            assert await comm_b.receive_nothing(timeout=0.2)

            await comm_a.disconnect()
            await comm_b.disconnect()

        run_async(scenario)


@pytest.mark.django_db(transaction=True)
class TestOrderServicesBroadcastWiring:
    """The actual integration point: apps/orders/services.py calling
    _broadcast_seat_update() at every place inventory changes."""

    def test_create_order_broadcasts_decreased_count(self, in_memory_channel_layer):
        from apps.orders import services as order_services

        event = EventFactory(total_capacity=20, tickets_sold=0)
        tier = TicketTierFactory(event=event, quantity=20, quantity_sold=0)
        buyer = UserFactory()

        async def scenario():
            communicator = WebsocketCommunicator(application, f"/ws/events/{event.slug}/seats/")
            await communicator.connect()
            await communicator.receive_from()  # initial: 20 remaining

            from asgiref.sync import sync_to_async
            from apps.orders.services import CheckoutItem

            await sync_to_async(order_services.create_order)(
                attendee=buyer, event=event, items=[CheckoutItem(tier.id, 3)]
            )

            message = await communicator.receive_from()
            assert json.loads(message) == {"seats_remaining": 17}

            await communicator.disconnect()

        run_async(scenario)

    def test_cancel_order_broadcasts_restored_count(self, in_memory_channel_layer):
        from apps.orders import services as order_services
        from apps.orders.models import OrderStatus

        event = EventFactory(total_capacity=20, tickets_sold=5)
        tier = TicketTierFactory(event=event, quantity_sold=5)
        order = OrderFactory(event=event, status=OrderStatus.PENDING)
        OrderItemFactory(order=order, tier=tier, quantity=5)

        async def scenario():
            communicator = WebsocketCommunicator(application, f"/ws/events/{event.slug}/seats/")
            await communicator.connect()
            await communicator.receive_from()  # initial: 15 remaining

            from asgiref.sync import sync_to_async

            await sync_to_async(order_services.cancel_order)(order=order, actor=order.attendee)

            message = await communicator.receive_from()
            assert json.loads(message) == {"seats_remaining": 20}

            await communicator.disconnect()

        run_async(scenario)

    def test_refund_order_broadcasts_restored_count(self, in_memory_channel_layer, monkeypatch):
        from apps.orders import services as order_services
        from apps.orders.models import OrderStatus

        monkeypatch.setattr(
            "apps.orders.payment.refund_payment_intent", lambda order: object()
        )

        event = EventFactory(total_capacity=20, tickets_sold=4)
        tier = TicketTierFactory(event=event, quantity_sold=4)
        order = OrderFactory(event=event, status=OrderStatus.CONFIRMED)
        OrderItemFactory(order=order, tier=tier, quantity=4)

        async def scenario():
            communicator = WebsocketCommunicator(application, f"/ws/events/{event.slug}/seats/")
            await communicator.connect()
            await communicator.receive_from()  # initial: 16 remaining

            from asgiref.sync import sync_to_async

            await sync_to_async(order_services.refund_order)(order=order, actor=order.attendee)

            message = await communicator.receive_from()
            assert json.loads(message) == {"seats_remaining": 20}

            await communicator.disconnect()

        run_async(scenario)

    def test_confirm_order_does_not_broadcast(self, in_memory_channel_layer):
        """confirm_order() never touches tickets_sold (already decremented
        at create_order time) -- per services/realtime.py's own docstring,
        it must not broadcast at all."""
        from apps.orders import services as order_services
        from apps.orders.models import OrderStatus

        event = EventFactory(total_capacity=20, tickets_sold=5)
        tier = TicketTierFactory(event=event, quantity_sold=5)
        order = OrderFactory(event=event, status=OrderStatus.PENDING)
        OrderItemFactory(order=order, tier=tier, quantity=5)

        async def scenario():
            communicator = WebsocketCommunicator(application, f"/ws/events/{event.slug}/seats/")
            await communicator.connect()
            await communicator.receive_from()  # initial count

            from asgiref.sync import sync_to_async

            await sync_to_async(order_services.confirm_order)(
                order=order, payment_intent_id="pi_no_broadcast"
            )

            assert await communicator.receive_nothing(timeout=0.3)

            await communicator.disconnect()

        run_async(scenario)
