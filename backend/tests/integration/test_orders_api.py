from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.orders.models import Order, OrderStatus, Ticket, TicketStatus
from tests.factories import (
    AdminFactory,
    EventFactory,
    OrderFactory,
    OrderItemFactory,
    TicketFactory,
    TicketTierFactory,
    UserFactory,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def attendee_client(api_client):
    user = UserFactory()
    api_client.force_authenticate(user=user)
    api_client._user = user
    return api_client


@pytest.fixture
def admin_client(api_client):
    user = AdminFactory()
    api_client.force_authenticate(user=user)
    api_client._user = user
    return api_client


@pytest.mark.django_db
class TestOrdersAPI:
    def test_create_order_success(self, attendee_client):
        event = EventFactory(status="PUBLISHED", tickets_sold=4)
        tier = TicketTierFactory(
            event=event,
            price=Decimal("15.00"),
            quantity=20,
            quantity_sold=2,
        )

        response = attendee_client.post(
            reverse("order-list"),
            {
                "event_slug": event.slug,
                "items": [{"tier_id": str(tier.id), "quantity": 3}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["event_slug"] == event.slug
        assert response.data["attendee_email"] == attendee_client._user.email
        assert response.data["status"] == OrderStatus.PENDING
        assert response.data["total_amount"] == "45.00"
        assert len(response.data["items"]) == 1
        assert len(response.data["items"][0]["tickets"]) == 3

        order = Order.objects.get(id=response.data["id"])
        assert order.attendee == attendee_client._user
        assert order.items.count() == 1
        assert Ticket.objects.filter(order_item__order=order).count() == 3

        tier.refresh_from_db()
        event.refresh_from_db()
        assert tier.quantity_sold == 5
        assert event.tickets_sold == 7

    def test_create_order_requires_authentication(self, api_client):
        response = api_client.post(reverse("order-list"), {}, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_order_rejects_duplicate_tier_items(self, attendee_client):
        event = EventFactory(status="PUBLISHED")
        tier = TicketTierFactory(event=event)

        response = attendee_client.post(
            reverse("order-list"),
            {
                "event_slug": event.slug,
                "items": [
                    {"tier_id": str(tier.id), "quantity": 1},
                    {"tier_id": str(tier.id), "quantity": 1},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["success"] is False
        assert response.data["errors"][0]["attr"] == "items"

    def test_create_order_returns_conflict_for_insufficient_inventory(self, attendee_client):
        event = EventFactory(status="PUBLISHED")
        tier = TicketTierFactory(event=event, quantity=2, quantity_sold=1)

        response = attendee_client.post(
            reverse("order-list"),
            {
                "event_slug": event.slug,
                "items": [{"tier_id": str(tier.id), "quantity": 2}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "detail" in response.data

    def test_list_orders_scopes_to_authenticated_attendee(self, attendee_client):
        mine = OrderFactory(attendee=attendee_client._user, status=OrderStatus.PENDING)
        other = OrderFactory(status=OrderStatus.PENDING)

        response = attendee_client.get(reverse("order-list"))

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"] if isinstance(response.data, dict) and "results" in response.data else response.data
        ids = {item["id"] for item in results}
        assert str(mine.id) in ids
        assert str(other.id) not in ids

    def test_retrieve_order_returns_detail_for_owner(self, attendee_client):
        order = OrderFactory(attendee=attendee_client._user)
        tier = TicketTierFactory(event=order.event, price=Decimal("12.00"))
        item = OrderItemFactory(order=order, tier=tier, quantity=2, unit_price=Decimal("12.00"))
        TicketFactory(order_item=item, attendee=order.attendee, event=order.event, tier=tier)
        TicketFactory(order_item=item, attendee=order.attendee, event=order.event, tier=tier)

        response = attendee_client.get(reverse("order-detail", kwargs={"id": order.id}))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(order.id)
        assert response.data["attendee_email"] == attendee_client._user.email
        assert len(response.data["items"]) == 1
        assert len(response.data["items"][0]["tickets"]) == 2

    def test_retrieve_order_hides_other_attendees_order(self, attendee_client):
        order = OrderFactory()

        response = attendee_client.get(reverse("order-detail", kwargs={"id": order.id}))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cancel_order_success(self, attendee_client):
        event = EventFactory(status="PUBLISHED", tickets_sold=2)
        tier = TicketTierFactory(event=event, quantity=10, quantity_sold=2)
        order = OrderFactory(
            attendee=attendee_client._user,
            event=event,
            status=OrderStatus.PENDING,
        )
        item = OrderItemFactory(order=order, tier=tier, quantity=2)
        ticket = TicketFactory(
            order_item=item,
            attendee=attendee_client._user,
            event=event,
            tier=tier,
            status=TicketStatus.VALID,
        )

        response = attendee_client.post(reverse("order-cancel", kwargs={"id": order.id}))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == OrderStatus.CANCELLED

        order.refresh_from_db()
        ticket.refresh_from_db()
        tier.refresh_from_db()
        event.refresh_from_db()

        assert order.status == OrderStatus.CANCELLED
        assert ticket.status == TicketStatus.CANCELLED
        assert tier.quantity_sold == 0
        assert event.tickets_sold == 0

    def test_cancel_order_with_used_ticket_returns_conflict(self, attendee_client):
        order = OrderFactory(attendee=attendee_client._user, status=OrderStatus.PENDING)
        item = OrderItemFactory(order=order)
        TicketFactory(order_item=item, status=TicketStatus.USED)

        response = attendee_client.post(reverse("order-cancel", kwargs={"id": order.id}))

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "detail" in response.data

    def test_confirm_order_requires_admin(self, attendee_client):
        order = OrderFactory(attendee=attendee_client._user, status=OrderStatus.PENDING)

        response = attendee_client.post(reverse("order-confirm", kwargs={"id": order.id}))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_confirm_order(self, admin_client):
        order = OrderFactory(
            status=OrderStatus.PENDING,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        response = admin_client.post(
            reverse("order-confirm", kwargs={"id": order.id}),
            {"payment_intent_id": "pi_test_123"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == OrderStatus.CONFIRM
        assert response.data["payment_intent_id"] == "pi_test_123"

        order.refresh_from_db()
        assert order.status == OrderStatus.CONFIRM
        assert order.payment_intent_id == "pi_test_123"
        assert order.expires_at is None
