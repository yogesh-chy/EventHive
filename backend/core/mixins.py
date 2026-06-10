"""
core/mixins.py  ·  PHASE 2

Reusable view mixins shared across all EventHive apps.

  OrgScopedMixin  — Enforce multi-tenancy at the queryset level.
  AuditLogMixin   — Write an AuditLog entry after state-changing requests.

Predicted problems addressed:
──────────────────────────────
1.  Organiser accidentally sees another org's data if the filter is
    applied inconsistently → OrgScopedMixin is applied at get_queryset()
    level, not at individual view methods. One place to change, one
    place to test.

2.  Admin bypass must be explicit, not implicit:
    → `if role == ADMIN: return queryset` at the top of apply_org_scope().
      If the role check is accidentally removed, the restriction still
      applies — it does not default to unrestricted.

3.  Membership lookup firing per-request (N+1 across requests):
    → org IDs are fetched once per request and stored in _cached_org_ids
      on the view instance. Multiple calls to apply_org_scope() within
      the same request reuse the cached list.

4.  Org membership check missing `org__is_active=True`:
    → Explicitly included so suspended orgs are excluded even if the
      user's Membership row still exists.

5.  AuditLog failure crashing a legitimate write request:
    → _write_audit() is wrapped in try/except. Audit failure is logged
      at ERROR level but never propagates to the caller.
"""

import logging
from typing import Any

from django.db.models import QuerySet

logger = logging.getLogger(__name__)

ADMIN_ROLE = "ADMIN"


# ── OrgScopedMixin ─────────────────────────────────────────────────────────────

class OrgScopedMixin:
    """
    Restrict queryset to organizations the authenticated user belongs to.

    Admins (role == 'ADMIN') bypass the filter and see all records.
    All other roles only see records belonging to their active memberships.

    How to use:
    ──────────
        class EventViewSet(OrgScopedMixin, viewsets.GenericViewSet):
            def get_queryset(self):
                return self.apply_org_scope(Event.objects.all())

    For nested routes where the org is inferred from the URL:
        org = self.get_org_from_url(org_id=self.kwargs["org_id"])
    """

    # Per-request cache — avoids repeated DB hits within one request cycle.
    _cached_org_ids: list[Any] | None = None

    def _get_user_org_ids(self) -> list:
        """
        Return a list of org PKs the current user is an active member of.
        Result is cached on the view instance for the duration of the request.
        """
        if self._cached_org_ids is None:
            self._cached_org_ids = list(
                self.request.user.membership_set.filter(  # type: ignore[attr-defined]
                    org__is_active=True,
                ).values_list("org_id", flat=True)
            )
        return self._cached_org_ids

    def apply_org_scope(self, queryset: QuerySet) -> QuerySet:
        """
        Filter a queryset so the user only sees rows belonging to their orgs.
        The queryset MUST have an `org_id` (or `org`) FK field.
        """
        user = self.request.user  # type: ignore[attr-defined]

        if getattr(user, "role", None) == ADMIN_ROLE:
            return queryset  # admins see everything

        org_ids = self._get_user_org_ids()

        if not org_ids:
            # User has no active memberships — return empty queryset.
            # Do NOT raise here; let the view return 200 with an empty list.
            return queryset.none()

        return queryset.filter(org_id__in=org_ids)

    def assert_org_access(self, org_id: Any) -> None:
        """
        Raise PermissionDenied if the user doesn't belong to `org_id`.
        Use this in create/update views where the org comes from the request
        body rather than from the queryset.
        """
        from rest_framework.exceptions import PermissionDenied

        user = self.request.user  # type: ignore[attr-defined]

        if getattr(user, "role", None) == ADMIN_ROLE:
            return  # admins always pass

        user_org_ids = {str(i) for i in self._get_user_org_ids()}
        if str(org_id) not in user_org_ids:
            raise PermissionDenied("You do not have access to this organization.")

    def get_org_from_url(self, org_id: Any):
        """
        Fetch an Organization the user has access to.
        Raises PermissionDenied or NotFound as appropriate.
        """
        from apps.organizations.models import Organization
        from rest_framework.exceptions import NotFound

        self.assert_org_access(org_id)

        try:
            return Organization.objects.get(pk=org_id, is_active=True)
        except Organization.DoesNotExist:
            raise NotFound("Organization not found.")


# ── AuditLogMixin ──────────────────────────────────────────────────────────────

class AuditLogMixin:
    """
    Automatically write an AuditLog row after successful create/update operations.

    Relies on apps.audit.services.write_audit_log() introduced in Phase 1.
    Override `audit_action` at the ViewSet level:

        class EventViewSet(AuditLogMixin, viewsets.GenericViewSet):
            audit_action = "EVENT"

    Writes:
      - EVENT_CREATED on perform_create()
      - EVENT_UPDATED on perform_update()

    Custom actions (publish, cancel) should call self._write_audit() directly.
    """

    audit_action: str = "OBJECT"

    def perform_create(self, serializer):
        instance = serializer.save()
        self._write_audit(instance, action=f"{self.audit_action}_CREATED")
        return instance

    def perform_update(self, serializer):
        instance = serializer.save()
        self._write_audit(instance, action=f"{self.audit_action}_UPDATED")
        return instance

    def _write_audit(self, instance: Any, action: str) -> None:
        """
        Write an audit log entry. Failures are swallowed and logged — they
        must never crash a legitimate business operation.
        """
        try:
            from apps.audit.services import write_audit_log
            write_audit_log(
                actor=self.request.user,  # type: ignore[attr-defined]
                action=action,
                entity=instance,
                request=self.request,  # type: ignore[attr-defined]
            )
        except Exception:
            logger.exception(
                "AuditLog write failed. action=%s instance=%r — "
                "business operation was NOT rolled back.",
                action,
                instance,
            )