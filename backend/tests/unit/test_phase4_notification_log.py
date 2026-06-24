"""
Phase 4: NotificationLog idempotency + the DB-level unique constraint it
relies on, since that constraint is what makes Beat-tick overlap and task
redelivery safe.
"""
import pytest
from django.db import IntegrityError

from apps.notifications.models import NotificationLog


@pytest.mark.django_db
class TestNotificationLogClaim:
    def test_first_claim_creates_pending_log(self):
        log, created = NotificationLog.claim(
            notification_type=NotificationLog.NotificationType.TICKET_CONFIRMATION,
            target_type="ticket",
            target_id="abc-1",
            recipient_email="a@example.com",
        )
        assert created is True
        assert log.status == NotificationLog.Status.PENDING

    def test_second_claim_reuses_the_same_row(self):
        log1, created1 = NotificationLog.claim(
            notification_type=NotificationLog.NotificationType.TICKET_CONFIRMATION,
            target_type="ticket",
            target_id="abc-2",
            recipient_email="a@example.com",
        )
        log1.mark_sent()

        log2, created2 = NotificationLog.claim(
            notification_type=NotificationLog.NotificationType.TICKET_CONFIRMATION,
            target_type="ticket",
            target_id="abc-2",
            recipient_email="a@example.com",
        )
        assert created2 is False
        assert log2.id == log1.id
        assert log2.status == NotificationLog.Status.SENT

    def test_different_notification_types_for_same_target_dont_collide(self):
        log1, _ = NotificationLog.claim(
            notification_type=NotificationLog.NotificationType.TICKET_CONFIRMATION,
            target_type="ticket",
            target_id="shared-1",
            recipient_email="a@example.com",
        )
        log2, _ = NotificationLog.claim(
            notification_type=NotificationLog.NotificationType.EVENT_REMINDER,
            target_type="ticket",
            target_id="shared-1",
            recipient_email="a@example.com",
        )
        assert log1.id != log2.id


@pytest.mark.django_db
class TestNotificationLogConstraint:
    def test_unique_constraint_enforced_at_db_level(self):
        """
        Bypassing claim() entirely and calling .objects.create() twice for
        the same target must still fail -- the safety here is the DB
        constraint, not application discipline about always going through
        claim().
        """
        NotificationLog.objects.create(
            notification_type=NotificationLog.NotificationType.EVENT_REMINDER,
            target_type="ticket",
            target_id="dup-1",
            recipient_email="a@example.com",
        )
        with pytest.raises(IntegrityError):
            NotificationLog.objects.create(
                notification_type=NotificationLog.NotificationType.EVENT_REMINDER,
                target_type="ticket",
                target_id="dup-1",
                recipient_email="b@example.com",
            )


@pytest.mark.django_db
class TestNotificationLogFailureTracking:
    def test_mark_failed_increments_attempts_and_records_error(self):
        log, _ = NotificationLog.claim(
            notification_type=NotificationLog.NotificationType.ABANDONED_CART,
            target_type="order",
            target_id="fail-1",
            recipient_email="a@example.com",
        )
        log.mark_failed("SMTP timeout")
        log.refresh_from_db()
        assert log.attempts == 1
        assert log.status == NotificationLog.Status.FAILED
        assert "SMTP timeout" in log.last_error

        log.mark_failed("SMTP timeout again")
        log.refresh_from_db()
        assert log.attempts == 2

    def test_claim_after_failure_returns_existing_failed_row_for_retry(self):
        log1, _ = NotificationLog.claim(
            notification_type=NotificationLog.NotificationType.ABANDONED_CART,
            target_type="order",
            target_id="fail-2",
            recipient_email="a@example.com",
        )
        log1.mark_failed("boom")

        log2, created = NotificationLog.claim(
            notification_type=NotificationLog.NotificationType.ABANDONED_CART,
            target_type="order",
            target_id="fail-2",
            recipient_email="a@example.com",
        )
        assert created is False
        assert log2.status == NotificationLog.Status.FAILED  # caller should retry, not skip
