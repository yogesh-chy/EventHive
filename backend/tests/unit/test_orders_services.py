import pytest
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from django.db.models import F

from apps.orders.models import Order, OrderItem, OrderStatus, Ticket, TicketStatus
from apps.orders.services import (
    create_order,
    confirm_order,
    cancel_order,
    expire_pending_orders,
    CheckoutItem,
)
from core.exceptions import (
    InsufficientInventoryError,
    InvalidStatusTransitionError,
    OrderAlreadyConfirmedError,
    OrderExpiredError,
    SeatAlreadyReservedError,
)
from tests.factories import (
    UserFactory,
    EventFactory,
    TicketTierFactory,
    OrderFactory,
    OrderItemFactory,
    TicketFactory,
)


@pytest.mark.django_db
class TestOrdersServices:
    def test_create_order_success(self):
        attendee = UserFactory()
        event = EventFactory(status="PUBLISHED", tickets_sold=0)
        tier = TicketTierFactory(event=event, price=Decimal("25.00"), quantity=10, quantity_sold=0)

        order = create_order(
            attendee=attendee,
            event=event,
            items=[CheckoutItem(tier_id=str(tier.id), quantity=2)],
        )

        assert order.status == OrderStatus.PENDING
        assert order.total_amount == Decimal("50.00")
        assert order.attendee == attendee
        assert order.event == event
        assert order.reference  # should be generated
        assert order.idempotency_key  # should be generated
        assert order.items.count() == 1
        assert Ticket.objects.filter(order_item__order=order).count() == 2

        tier.refresh_from_db()
        event.refresh_from_db()
        assert tier.quantity_sold == 2
        assert event.tickets_sold == 2

    def test_create_order_duplicate_pending_order_raises_error(self):
        attendee = UserFactory()
        event = EventFactory(status="PUBLISHED")
        tier = TicketTierFactory(event=event, quantity=10, quantity_sold=0)

        create_order(
            attendee=attendee,
            event=event,
            items=[CheckoutItem(tier_id=str(tier.id), quantity=1)],
        )

        with pytest.raises(SeatAlreadyReservedError):
            create_order(
                attendee=attendee,
                event=event,
                items=[CheckoutItem(tier_id=str(tier.id), quantity=1)],
            )

    def test_create_order_insufficient_inventory_raises_error(self):
        attendee = UserFactory()
        event = EventFactory(status="PUBLISHED")
        tier = TicketTierFactory(event=event, quantity=5, quantity_sold=4)

        with pytest.raises(InsufficientInventoryError):
            create_order(
                attendee=attendee,
                event=event,
                items=[CheckoutItem(tier_id=str(tier.id), quantity=2)],
            )

    def test_create_order_inactive_tier_raises_error(self):
        attendee = UserFactory()
        event = EventFactory(status="PUBLISHED")
        tier = TicketTierFactory(event=event, is_active=False)

        with pytest.raises(InsufficientInventoryError):
            create_order(
                attendee=attendee,
                event=event,
                items=[CheckoutItem(tier_id=str(tier.id), quantity=1)],
            )

    def test_create_order_outside_sales_window_raises_error(self):
        attendee = UserFactory()
        event = EventFactory(status="PUBLISHED")
        tier_past = TicketTierFactory(
            event=event,
            sale_start=timezone.now() - timedelta(days=10),
            sale_end=timezone.now() - timedelta(days=1),
        )

        with pytest.raises(InsufficientInventoryError):
            create_order(attendee=attendee, event=event, items=[CheckoutItem(tier_id=str(tier_past.id), quantity=1)])

    def test_confirm_order_success(self):
        order = OrderFactory(status=OrderStatus.PENDING, expires_at=timezone.now() + timedelta(minutes=5))

        confirmed = confirm_order(order=order, payment_intent_id="pi_12345")

        assert confirmed.status == OrderStatus.CONFIRMED
        assert confirmed.stripe_payment_intent_id == "pi_12345"
        assert confirmed.expires_at is None

    def test_confirm_expired_order_raises_error(self):
        order = OrderFactory(status=OrderStatus.PENDING, expires_at=timezone.now() - timedelta(minutes=1))

        with pytest.raises(OrderExpiredError):
            confirm_order(order=order)

    def test_confirm_non_pending_order_raises_error(self):
        order_confirmed = OrderFactory(status=OrderStatus.CONFIRMED)
        with pytest.raises(InvalidStatusTransitionError):
            confirm_order(order=order_confirmed)

    def test_cancel_order_success(self):
        event = EventFactory(status="PUBLISHED", tickets_sold=5)
        tier = TicketTierFactory(event=event, quantity=10, quantity_sold=5)
        actor = UserFactory()

        order = OrderFactory(event=event, status=OrderStatus.PENDING)
        item = OrderItemFactory(order=order, tier=tier, quantity=2)
        TicketFactory(order_item=item, attendee=order.attendee, event=event, tier=tier, status=TicketStatus.VALID)
        TicketFactory(order_item=item, attendee=order.attendee, event=event, tier=tier, status=TicketStatus.VALID)

        cancelled = cancel_order(order=order, actor=actor)

        assert cancelled.status == OrderStatus.CANCELLED

        tier.refresh_from_db()
        event.refresh_from_db()
        assert tier.quantity_sold == 3
        assert event.tickets_sold == 3

        assert Ticket.objects.filter(order_item__order=order, status=TicketStatus.CANCELLED).count() == 2

    def test_cancel_order_with_used_tickets_fails(self):
        order = OrderFactory(status=OrderStatus.PENDING)
        item = OrderItemFactory(order=order)
        TicketFactory(order_item=item, attendee=order.attendee, event=order.event, tier=item.tier, status=TicketStatus.USED)

        with pytest.raises(InvalidStatusTransitionError):
            cancel_order(order=order, actor=order.attendee)

    def test_cancel_already_confirmed_order_raises_error(self):
        order = OrderFactory(status=OrderStatus.CONFIRMED)

        with pytest.raises(OrderAlreadyConfirmedError):
            cancel_order(order=order, actor=order.attendee)

    def test_expire_pending_orders(self):
        event = EventFactory(status="PUBLISHED", tickets_sold=2)
        tier = TicketTierFactory(event=event, quantity_sold=5)

        # Expired pending order
        order1 = OrderFactory(event=event, status=OrderStatus.PENDING, expires_at=timezone.now() - timedelta(minutes=5))
        OrderItemFactory(order=order1, tier=tier, quantity=2)

        # Non-expired pending order
        order2 = OrderFactory(event=event, status=OrderStatus.PENDING, expires_at=timezone.now() + timedelta(minutes=5))
        OrderItemFactory(order=order2, tier=tier, quantity=1)

        # Confirmed order (already expired timestamp)
        order3 = OrderFactory(event=event, status=OrderStatus.CONFIRMED, expires_at=timezone.now() - timedelta(minutes=5))

        count = expire_pending_orders()

        assert count == 1
        order1.refresh_from_db()
        order2.refresh_from_db()
        order3.refresh_from_db()

        assert order1.status == OrderStatus.CANCELLED
        assert order2.status == OrderStatus.PENDING
        assert order3.status == OrderStatus.CONFIRMED
