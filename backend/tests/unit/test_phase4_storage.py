"""
Phase 4: services/storage.py against a moto-mocked S3, never real AWS.
"""
import boto3
import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def s3_settings(settings):
    settings.AWS_ACCESS_KEY_ID = "testing"
    settings.AWS_SECRET_ACCESS_KEY = "testing"
    settings.AWS_STORAGE_BUCKET_NAME = "eventhive-test-storage"
    settings.AWS_S3_ENDPOINT_URL = None

    # services.storage caches its boto3 client at module level (see its
    # docstring on fork-safety) -- reset between tests so each test's moto
    # mock gets its own freshly-built client rather than reusing one bound
    # to a previous test's (already torn down) mocked AWS backend.
    import services.storage as storage_module

    storage_module._client = None
    yield
    storage_module._client = None


class TestBuildTicketPdfKey:
    def test_deterministic(self):
        from services.storage import build_ticket_pdf_key

        key1 = build_ticket_pdf_key(org_slug="acme", event_slug="launch", ticket_id="abc-123")
        key2 = build_ticket_pdf_key(org_slug="acme", event_slug="launch", ticket_id="abc-123")
        assert key1 == key2
        assert key1 == "tickets/acme/launch/abc-123.pdf"

    def test_namespaced_by_org_and_event(self):
        from services.storage import build_ticket_pdf_key

        key_a = build_ticket_pdf_key(org_slug="acme", event_slug="launch", ticket_id="same-id")
        key_b = build_ticket_pdf_key(org_slug="other-org", event_slug="launch", ticket_id="same-id")
        assert key_a != key_b


class TestUploadAndPresignedUrl:
    def test_roundtrip(self):
        from services.storage import generate_presigned_url, upload_bytes

        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(
                Bucket="eventhive-test-storage"
            )
            upload_bytes(key="tickets/acme/launch/abc.pdf", data=b"%PDF-fake-content")

            url = generate_presigned_url(key="tickets/acme/launch/abc.pdf", expires_in=600)

            assert url.startswith("https://")
            assert "eventhive-test-storage" in url
            assert "Signature" in url

    def test_retried_upload_overwrites_same_key(self):
        """Idempotency property the whole design leans on: re-uploading to
        the same deterministic key replaces the object rather than erroring
        or creating a duplicate."""
        from services.storage import generate_presigned_url, upload_bytes

        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(
                Bucket="eventhive-test-storage"
            )
            upload_bytes(key="tickets/acme/launch/abc.pdf", data=b"version-1")
            upload_bytes(key="tickets/acme/launch/abc.pdf", data=b"version-2")

            client = boto3.client("s3", region_name="us-east-1")
            body = client.get_object(Bucket="eventhive-test-storage", Key="tickets/acme/launch/abc.pdf")[
                "Body"
            ].read()
            assert body == b"version-2"


class TestPresignedUrlEdgeCases:
    def test_empty_key_returns_empty_string_not_an_error(self):
        from services.storage import generate_presigned_url

        assert generate_presigned_url(key="") == ""

    def test_none_key_returns_empty_string_not_an_error(self):
        from services.storage import generate_presigned_url

        assert generate_presigned_url(key=None) == ""
