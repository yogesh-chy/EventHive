import pytest
from unittest import mock
from django.test import RequestFactory
from django.core.cache import cache

from core.cache import acquire_seat_lock
from core.exceptions import SeatAlreadyReservedError
from core.throttles import TicketPurchaseThrottle, PasswordResetEmailThrottle
from apps.orders.services import create_order, CheckoutItem
from tests.factories import UserFactory, EventFactory, TicketTierFactory


@pytest.mark.django_db
class TestSeatLockRestoration:
    def test_create_order_fails_if_seat_lock_already_held(self):
        attendee = UserFactory()
        event = EventFactory(status="PUBLISHED")
        tier = TicketTierFactory(event=event, quantity=10, quantity_sold=0)

        # Manually acquire lock first to simulate concurrent lock hold
        assert acquire_seat_lock(str(tier.id), str(attendee.id), 1) is True

        # Now create_order should fail because the lock is already held
        with pytest.raises(SeatAlreadyReservedError):
            create_order(
                attendee=attendee,
                event=event,
                items=[CheckoutItem(tier_id=str(tier.id), quantity=1)],
            )


class TestThrottlesInIsolation:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        cache.clear()
        yield
        cache.clear()

    def test_ticket_purchase_throttle(self):
        throttle = TicketPurchaseThrottle()
        rf = RequestFactory()
        user = UserFactory.build(pk=999)

        # Request 1-10 should be allowed
        for _ in range(10):
            request = rf.post("/api/v1/orders/")
            request.user = user
            assert throttle.allow_request(request, None) is True

        # Request 11 should be throttled
        request = rf.post("/api/v1/orders/")
        request.user = user
        assert throttle.allow_request(request, None) is False

    def test_password_reset_email_throttle(self):
        throttle = PasswordResetEmailThrottle()
        rf = RequestFactory()

        # 5 attempts allowed for TEST@example.com
        for _ in range(5):
            request = rf.post("/api/v1/auth/password/reset/")
            request.data = {"email": "TEST@example.com"}
            assert throttle.allow_request(request, None) is True

        # 6th attempt should be throttled (case-insensitive check)
        request = rf.post("/api/v1/auth/password/reset/")
        request.data = {"email": "test@example.com"}
        assert throttle.allow_request(request, None) is False

        # A different email address is still allowed
        request = rf.post("/api/v1/auth/password/reset/")
        request.data = {"email": "other@example.com"}
        assert throttle.allow_request(request, None) is True
