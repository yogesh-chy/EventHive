"""
apps/audit/services.py  ·  PHASE 1

Service function for writing audit log entries.

Called by:
  - core.mixins.AuditLogMixin  (automatic on ViewSet create/update)
  - Directly from service functions for custom actions (publish, cancel, refund)

Failure to write an audit log NEVER crashes the calling operation.
The try/except in AuditLogMixin._write_audit() is the outer safety net;
this module adds its own inner safety net for direct callers.
"""

import logging

from django.http import HttpRequest

from core.middleware import get_current_ip

logger = logging.getLogger(__name__)


def write_audit_log(
    *,
    actor,
    action: str,
    entity,
    request: HttpRequest | None = None,
    diff: dict | None = None,
) -> None:
    """
    Write an immutable audit log entry.

    Args:
        actor:   The User who performed the action.
        action:  Action string, e.g. "EVENT_CREATED".
        entity:  The model instance affected.
        request: Optional HTTP request for IP / user-agent extraction.
        diff:    Optional before/after state dict.
    """
    # Late import to avoid circular dependency (audit ← core ← apps)
    from apps.audit.models import AuditLog

    ip_address = None
    user_agent = ""

    if request is not None:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        ip_address = (
            forwarded.split(",")[0].strip()
            if forwarded
            else request.META.get("REMOTE_ADDR")
        )
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]
    else:
        # Fall back to middleware thread-local context
        ip_address = get_current_ip()

    try:
        AuditLog.objects.create(
            actor=actor if (actor and actor.is_authenticated) else None,
            action=action,
            entity_type=entity.__class__.__name__,
            entity_id=str(entity.pk),
            diff=diff,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except Exception:
        logger.exception(
            "Failed to write audit log: action=%s entity=%s",
            action,
            f"{entity.__class__.__name__}#{entity.pk}",
        )
