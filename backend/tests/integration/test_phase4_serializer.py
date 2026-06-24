"""
Phase 4: TicketSerializer.pdf_url must return a working presigned URL,
not the raw S3 object key the model field actually stores.
"""
import boto3
import pytest
from moto import mock_aws

from apps.orders import services as order_services
from apps.orders.models import OrderStatus
from apps.orders.serializers import OrderDetailSerializer
from tests.factories import EventFactory, OrderFactory, OrderItemFactory, TicketFactory, TicketTierFactory


@pytest.fixture(autouse=True)
def phase4_env(settings):
    settings.AWS_ACCESS_KEY_ID = "testing"
    settings.AWS_SECRET_ACCESS_KEY = "testing"
    settings.AWS_STORAGE_BUCKET_NAME = "eventhive-test-serializer"

    import services.storage as storage_module

    storage_module._client = None
    yield
    storage_module._client = None


@pytest.mark.django_db
class TestTicketSerializerPdfUrl:
    def test_returns_working_presigned_link_not_raw_key(
        self, settings, django_capture_on_commit_callbacks
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(
                Bucket="eventhive-test-serializer"
            )

            event = EventFactory()
            tier = TicketTierFactory(event=event)
            order = OrderFactory(event=event, status=OrderStatus.PENDING)
            item = OrderItemFactory(order=order, tier=tier, quantity=1)
            TicketFactory(order_item=item, event=event, tier=tier, attendee_email="x@example.com")

            # See test_phase4_tasks.py for why this fixture is required:
            # confirm_order()'s transaction.on_commit dispatch never fires
            # inside the default rolled-back test transaction without it.
            with django_capture_on_commit_callbacks(execute=True):
                order_services.confirm_order(order=order, payment_intent_id="pi_serializer")

            data = OrderDetailSerializer(order).data
            pdf_url = data["items"][0]["tickets"][0]["pdf_url"]

            assert pdf_url.startswith("https://")
            assert "Signature" in pdf_url
            # the raw object key must never be returned by itself
            raw_key = f"tickets/{event.org.slug}/{event.slug}"
            assert pdf_url != raw_key
            assert "?X-Amz-" in pdf_url  # actually presigned, not a bare path

    def test_returns_none_before_assets_are_generated(self, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = False  # don't actually run the task
        event = EventFactory()
        tier = TicketTierFactory(event=event)
        order = OrderFactory(event=event, status=OrderStatus.PENDING)
        item = OrderItemFactory(order=order, tier=tier, quantity=1)
        TicketFactory(order_item=item, event=event, tier=tier, attendee_email="y@example.com")

        data = OrderDetailSerializer(order).data

        assert data["items"][0]["tickets"][0]["pdf_url"] is None
