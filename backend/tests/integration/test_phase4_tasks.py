"""
Phase 4: end-to-end tests for the async pipeline -- ticket asset
generation, the chained confirmation email, and the two Beat-scheduled
sweeps -- against a moto-mocked S3 bucket and Celery in eager mode.
"""
import datetime

import boto3
import pytest
from django.core import mail
from django.utils import timezone
from moto import mock_aws

from apps.notifications.models import NotificationLog
from apps.orders import services as order_services
from apps.orders.models import Order, OrderStatus
from tasks.notifications import (
    dispatch_abandoned_cart_emails_task,
    dispatch_event_reminders_task,
)
from tasks.tickets import generate_ticket_assets_task
from tests.factories import (
    EventFactory,
    OrderFactory,
    OrderItemFactory,
    TicketFactory,
    TicketTierFactory,
)


@pytest.fixture(autouse=True)
def phase4_env(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    settings.AWS_ACCESS_KEY_ID = "testing"
    settings.AWS_SECRET_ACCESS_KEY = "testing"
    settings.AWS_STORAGE_BUCKET_NAME = "eventhive-test-tasks"

    import services.storage as storage_module

    storage_module._client = None
    yield
    storage_module._client = None


@pytest.fixture
def s3_bucket():
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="eventhive-test-tasks")
        yield


@pytest.mark.django_db
class TestGenerateTicketAssetsTask:
    def test_generates_pdf_and_sets_pdf_url(self, s3_bucket):
        event = EventFactory()
        tier = TicketTierFactory(event=event)
        order = OrderFactory(event=event, status=OrderStatus.CONFIRMED)
        item = OrderItemFactory(order=order, tier=tier, quantity=1)
        ticket = TicketFactory(order_item=item, event=event, tier=tier, attendee_email="t@example.com")

        assert ticket.pdf_url == ""

        key = generate_ticket_assets_task(str(ticket.id))

        ticket.refresh_from_db()
        assert ticket.pdf_url == key
        assert ticket.pdf_url == f"tickets/{event.org.slug}/{event.slug}/{ticket.id}.pdf"

    def test_idempotent_on_redelivery(self, s3_bucket):
        """Simulates CELERY_TASK_ACKS_LATE redelivering the same task after
        a worker crash post-upload, pre-ack."""
        event = EventFactory()
        tier = TicketTierFactory(event=event)
        order = OrderFactory(event=event, status=OrderStatus.CONFIRMED)
        item = OrderItemFactory(order=order, tier=tier, quantity=1)
        ticket = TicketFactory(order_item=item, event=event, tier=tier, attendee_email="t@example.com")

        key1 = generate_ticket_assets_task(str(ticket.id))
        key2 = generate_ticket_assets_task(str(ticket.id))

        assert key1 == key2
        # exactly one confirmation email, not two, on the redelivered run
        assert len(mail.outbox) == 1

    def test_chains_to_confirmation_email(self, s3_bucket):
        event = EventFactory()
        tier = TicketTierFactory(event=event)
        order = OrderFactory(event=event, status=OrderStatus.CONFIRMED)
        item = OrderItemFactory(order=order, tier=tier, quantity=1)
        ticket = TicketFactory(order_item=item, event=event, tier=tier, attendee_email="chained@example.com")

        generate_ticket_assets_task(str(ticket.id))

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["chained@example.com"]
        log = NotificationLog.objects.get(
            notification_type=NotificationLog.NotificationType.TICKET_CONFIRMATION,
            target_id=str(ticket.id),
        )
        assert log.status == NotificationLog.Status.SENT


@pytest.mark.django_db
class TestConfirmOrderTriggersAssetGeneration:
    """The actual integration point: apps.orders.services.confirm_order()."""

    def test_single_ticket_order(self, s3_bucket, django_capture_on_commit_callbacks):
        event = EventFactory()
        tier = TicketTierFactory(event=event)
        order = OrderFactory(event=event, status=OrderStatus.PENDING)
        item = OrderItemFactory(order=order, tier=tier, quantity=1)
        ticket = TicketFactory(order_item=item, event=event, tier=tier, attendee_email="confirm@example.com")

        # confirm_order() defers ticket-asset dispatch via transaction.on_commit
        # (deliberately -- see apps/orders/services.py docstring). The default
        # @pytest.mark.django_db wraps each test in a transaction that's rolled
        # back, not committed, so on_commit callbacks never fire without this
        # fixture explicitly capturing and running them.
        with django_capture_on_commit_callbacks(execute=True):
            order_services.confirm_order(order=order, payment_intent_id="pi_abc")

        ticket.refresh_from_db()
        assert ticket.pdf_url
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["confirm@example.com"]

    def test_multi_ticket_order_generates_assets_for_every_ticket(
        self, s3_bucket, django_capture_on_commit_callbacks
    ):
        """OrderItem quantity layer: confirming one order with N tickets
        must fan out into N independent asset-generation + email tasks."""
        event = EventFactory()
        tier = TicketTierFactory(event=event)
        order = OrderFactory(event=event, status=OrderStatus.PENDING)
        item = OrderItemFactory(order=order, tier=tier, quantity=3)
        tickets = [
            TicketFactory(order_item=item, event=event, tier=tier, attendee_email=f"t{i}@example.com")
            for i in range(3)
        ]

        with django_capture_on_commit_callbacks(execute=True):
            order_services.confirm_order(order=order, payment_intent_id="pi_multi")

        for t in tickets:
            t.refresh_from_db()
            assert t.pdf_url

        assert len(mail.outbox) == 3
        sent_to = {m.to[0] for m in mail.outbox}
        assert sent_to == {"t0@example.com", "t1@example.com", "t2@example.com"}


@pytest.mark.django_db
class TestDispatchEventReminders:
    def test_sends_for_event_24h_away(self):
        event = EventFactory(start_datetime=timezone.now() + datetime.timedelta(hours=24, minutes=5))
        tier = TicketTierFactory(event=event)
        order = OrderFactory(event=event, status=OrderStatus.CONFIRMED)
        item = OrderItemFactory(order=order, tier=tier, quantity=1)
        ticket = TicketFactory(order_item=item, event=event, tier=tier, attendee_email="reminder@example.com")

        dispatch_event_reminders_task()

        assert len(mail.outbox) == 1
        log = NotificationLog.objects.get(
            notification_type=NotificationLog.NotificationType.EVENT_REMINDER,
            target_id=str(ticket.id),
        )
        assert log.status == NotificationLog.Status.SENT

    def test_skips_event_far_in_future(self):
        event = EventFactory(start_datetime=timezone.now() + datetime.timedelta(days=10))
        tier = TicketTierFactory(event=event)
        order = OrderFactory(event=event, status=OrderStatus.CONFIRMED)
        item = OrderItemFactory(order=order, tier=tier, quantity=1)
        TicketFactory(order_item=item, event=event, tier=tier, attendee_email="far@example.com")

        dispatch_event_reminders_task()

        assert len(mail.outbox) == 0

    def test_skips_pending_order(self):
        """A reminder shouldn't go out for a ticket attached to an order
        that was never actually confirmed."""
        event = EventFactory(start_datetime=timezone.now() + datetime.timedelta(hours=24, minutes=5))
        tier = TicketTierFactory(event=event)
        order = OrderFactory(event=event, status=OrderStatus.PENDING)
        item = OrderItemFactory(order=order, tier=tier, quantity=1)
        TicketFactory(order_item=item, event=event, tier=tier, attendee_email="pending@example.com")

        dispatch_event_reminders_task()

        assert len(mail.outbox) == 0

    def test_repeated_dispatch_does_not_double_send(self):
        """Two overlapping Beat ticks scanning the same still-open window
        must not double-email the same ticket."""
        event = EventFactory(start_datetime=timezone.now() + datetime.timedelta(hours=24, minutes=5))
        tier = TicketTierFactory(event=event)
        order = OrderFactory(event=event, status=OrderStatus.CONFIRMED)
        item = OrderItemFactory(order=order, tier=tier, quantity=1)
        TicketFactory(order_item=item, event=event, tier=tier, attendee_email="twice@example.com")

        dispatch_event_reminders_task()
        dispatch_event_reminders_task()

        assert len(mail.outbox) == 1


@pytest.mark.django_db
class TestDispatchAbandonedCartEmails:
    def test_sends_for_order_past_threshold_but_before_expiry(self, settings):
        order = OrderFactory(status=OrderStatus.PENDING)
        Order.objects.filter(id=order.id).update(
            created_at=timezone.now()
            - datetime.timedelta(minutes=settings.ABANDONED_CART_AFTER_MINUTES + 1)
        )

        dispatch_abandoned_cart_emails_task()

        assert len(mail.outbox) == 1
        log = NotificationLog.objects.get(
            notification_type=NotificationLog.NotificationType.ABANDONED_CART,
            target_id=str(order.id),
        )
        assert log.status == NotificationLog.Status.SENT
        assert mail.outbox[0].to == [order.attendee.email]

    def test_excludes_order_past_expiry_cutoff(self):
        """Must never email about a cart that expiry has already (or is
        about to) cancel and release the seat lock for."""
        from apps.orders.services import ORDER_EXPIRY_MINUTES

        order = OrderFactory(status=OrderStatus.PENDING)
        Order.objects.filter(id=order.id).update(
            created_at=timezone.now() - datetime.timedelta(minutes=ORDER_EXPIRY_MINUTES + 1)
        )

        dispatch_abandoned_cart_emails_task()

        assert len(mail.outbox) == 0
        assert not NotificationLog.objects.filter(target_id=str(order.id)).exists()

    def test_excludes_order_too_recent_to_count_as_abandoned(self):
        OrderFactory(status=OrderStatus.PENDING)  # just created

        dispatch_abandoned_cart_emails_task()

        assert len(mail.outbox) == 0

    def test_excludes_confirmed_order(self, settings):
        order = OrderFactory(status=OrderStatus.CONFIRMED)
        Order.objects.filter(id=order.id).update(
            created_at=timezone.now()
            - datetime.timedelta(minutes=settings.ABANDONED_CART_AFTER_MINUTES + 1)
        )

        dispatch_abandoned_cart_emails_task()

        assert len(mail.outbox) == 0
