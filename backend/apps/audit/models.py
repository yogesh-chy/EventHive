"""
apps/audit/models.py  ·  PHASE 1

Append-only audit trail for all state-changing operations.

Design decisions:
─────────────────
1.  NOT inheriting BaseModel — AuditLog should never be soft-deleted
    or updated. It has its own id, created_at, and no updated_at.

2.  save() and delete() are overridden to enforce immutability.
    Once a row is written, it cannot be changed or removed.

3.  default_permissions = ("add", "view") — Django admin cannot
    offer delete or change actions for this model.

4.  actor is SET_NULL on user deletion — the audit trail survives
    even after the actor account is removed.
"""

import uuid

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """
    Immutable audit log entry.

    Written by apps.audit.services.write_audit_log() via the
    AuditLogMixin on ViewSets, or directly from service functions.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        help_text="User who performed the action. Null for system actions.",
    )
    action = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Action identifier, e.g. EVENT_CREATED, ORDER_CONFIRMED.",
    )
    entity_type = models.CharField(
        max_length=100,
        help_text="Model class name, e.g. 'Event', 'Order'.",
    )
    entity_id = models.CharField(
        max_length=255,
        help_text="Primary key of the affected entity (UUID as string).",
    )
    diff = models.JSONField(
        null=True,
        blank=True,
        help_text="Before/after state snapshot. Null for create actions.",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["actor", "created_at"]),
        ]
        # Prevent Django admin from offering delete/change actions
        default_permissions = ("add", "view")

    def __str__(self):
        return f"[{self.action}] {self.entity_type}#{self.entity_id} by {self.actor_id}"

    # ── Immutability enforcement ──────────────────────────────────────────

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError(
                "AuditLog records are immutable. Updates are not allowed."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "AuditLog records are immutable. Deletion is not allowed."
        )
