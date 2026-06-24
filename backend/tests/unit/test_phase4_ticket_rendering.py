"""
Phase 4: services/ticket.py is pure -- no DB, no Celery, no settings
dependency -- so these are plain unit tests on bytes in, bytes out.
"""
import datetime

from services.ticket import generate_qr_png_bytes, render_ticket_pdf


class TestQRGeneration:
    def test_generates_valid_png(self):
        data = generate_qr_png_bytes("some-qr-token")
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(data) > 0

    def test_different_payloads_produce_different_images(self):
        a = generate_qr_png_bytes("token-a")
        b = generate_qr_png_bytes("token-b")
        assert a != b

    def test_same_payload_is_deterministic(self):
        a = generate_qr_png_bytes("token-stable")
        b = generate_qr_png_bytes("token-stable")
        assert a == b


class TestTicketPDFRendering:
    def test_generates_valid_pdf(self):
        pdf = render_ticket_pdf(
            qr_payload="qr-token-123",
            event_title="Test Event",
            event_starts_at=datetime.datetime(2026, 8, 1, 19, 0, tzinfo=datetime.timezone.utc),
            venue="Test Venue",
            attendee_name="Jane Doe",
            tier_name="VIP",
            order_reference="ORDREF01",
        )
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 1000  # sanity: not an empty/broken document

    def test_handles_long_strings_without_error(self):
        """
        Event titles/venues are user-supplied free text with no length cap
        enforced before reaching this function -- it must not crash on
        long input, only truncate what it displays.
        """
        pdf = render_ticket_pdf(
            qr_payload="qr-token-456",
            event_title="A" * 200,
            event_starts_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
            venue="V" * 200,
            attendee_name="N" * 200,
            tier_name="T" * 100,
            order_reference="REF",
        )
        assert pdf[:5] == b"%PDF-"

    def test_handles_empty_venue(self):
        """Venue is a required model field today, but render_ticket_pdf
        shouldn't itself assume a truthy value -- defensive against future
        schema relaxation."""
        pdf = render_ticket_pdf(
            qr_payload="qr-token-789",
            event_title="Event",
            event_starts_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
            venue="",
            attendee_name="Name",
            tier_name="Tier",
            order_reference="REF",
        )
        assert pdf[:5] == b"%PDF-"
