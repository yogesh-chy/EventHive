import logging
from typing import Any

from django.db.models import QuerySet

logger = logging.getLogger(__name__)

ADMIN_ROLE = "ADMIN"


# ---- OrgScopedMixin ----

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


# ---- AuditLogMixin ----

class AuditLogMixin:
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


# ---- AttendeeOrderMixin ----

class AttendeeOrderMixin:
    # Scope order queryset to request.user. Admins see all. (Phase 3)

    def apply_attendee_scope(self, queryset):
        user = self.request.user
        if getattr(user, "role", None) == ADMIN_ROLE:
            return queryset
        return queryset.filter(attendee=user)