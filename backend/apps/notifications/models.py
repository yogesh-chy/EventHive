import uuid

from django.db import models, transaction
from django.utils import timezone


class NotificationLog(models.Model):

    class NotificationType(models.TextChoices):
        TICKET_CONFIRMATION = "ticket_confirmation", "Ticket Confirmation"
        EVENT_REMINDER = "event_reminder", "Event Reminder"
        ABANDONED_CART = "abandoned_cart", "Abandoned Cart"
    
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification_type = models.CharField(max_length=32, choices=NotificationType.choices, db_index=True)
    target_type = models.CharField(max_length=32)
    target_id = models.CharField(max_length=64)
    recipient_email = models.EmailField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields = ["notification_type", "target_type", "target_id"],
                name = "uniq_notifiaction_per_target"
            )
        ]
        indexes = [
            models.Index(
                fields=["notification_type", "target_type", "target_id"],
                name = "notif_type_target_idx"
            ),
            models.Index(fields=["status", "created_at"], name="notif_status_created_idx")
        ]
    
    def __str__(self):
        return f"{self.notification_type}:{self.target_type}:{self.target_type} [{self.status}]"
    
    @classmethod
    def claim(cls, *, notification_type, target_type, target_id, recipient_email):
        with transaction.atomic():
            log, created = cls.objects.select_for_update().get_or_create(
                notification_type=notification_type,
                target_type=target_type,
                target_id=str(target_id),
                defaults={"recipient_email": recipient_email}
            )
        return log, created
    
    def mark_sent(self):
        self.status = self.Status.SENT
        self.sent_at = timezone.now()
        self.save(update_fields=["status", "sent_at"])

    def mark_failed(self, error: str):
        self.attempts +=1
        self.status = self.Status.FAILED
        self.last_error = (error or "")[:2000]
        self.save(update_fields=["attempts", "status", "last_error"])