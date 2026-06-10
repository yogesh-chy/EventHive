"""
core/permissions.py  ·  PHASE 2

All custom DRF permission classes for EventHive.

Role hierarchy (stored on User.role):
  ADMIN      — platform staff; bypasses all org/object-level restrictions
  ORGANIZER  — creates & manages events within their org(s)
  ATTENDEE   — purchases tickets; no write access to events

Predicted problems addressed:
──────────────────────────────
1.  AnonymousUser has no .role attribute → getattr(user, "role", None)
    is used everywhere; AttributeError can never occur.

2.  Organizer updating an event from a different org via a direct PATCH:
    → IsEventOrganizer checks has_object_permission() against the event's
      org FK, not just the user's role. Two-layer defence:
        Layer 1: OrgScopedMixin scopes the queryset (event not found → 404)
        Layer 2: IsEventOrganizer confirms org membership (→ 403)

3.  Inactive org members retaining access:
    → membership_set filter always includes org__is_active=True.

4.  Magic role strings spread across codebase:
    → Defined as module-level constants (ADMIN_ROLE, ORGANIZER_ROLE,
      ATTENDEE_ROLE). Import these, never write the strings inline.

5.  has_object_permission() never called if has_permission() returns False:
    → DRF short-circuits correctly. Both methods are implemented on every
      class that does object-level checks so behaviour is explicit.

6.  Permission class __init__ not compatible with DRF's as_view():
    → No custom __init__ on any permission class; DRF instantiates them.
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS

# ── Role constants ─────────────────────────────────────────────────────────────
# Import these from here — never hardcode role strings in views/services.
ADMIN_ROLE     = "ADMIN"
ORGANIZER_ROLE = "ORGANIZER"
ATTENDEE_ROLE  = "ATTENDEE"


# ── Helper ─────────────────────────────────────────────────────────────────────

def _user_org_ids(user) -> set:
    """Return set of org PKs (as strings) the user has active membership in."""
    return {
        str(pk)
        for pk in user.membership_set.filter(
            org__is_active=True,
        ).values_list("org_id", flat=True)
    }


# ── Platform-level permissions ─────────────────────────────────────────────────

class IsAdminUser(BasePermission):
    """
    Grant access only to platform admins (role == ADMIN).
    Use for internal dashboards, user management, and audit endpoints.
    """
    message = "You must be a platform administrator to perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "role", None) == ADMIN_ROLE
        )


class IsOrganizer(BasePermission):
    """
    Grant access to ORGANIZER or ADMIN.
    Use on endpoints that create/manage resources (events, tiers).
    """
    message = "You must be an organizer to perform this action."

    def has_permission(self, request, view):
        role = getattr(request.user, "role", None)
        return bool(
            request.user
            and request.user.is_authenticated
            and role in (ORGANIZER_ROLE, ADMIN_ROLE)
        )


class IsAttendee(BasePermission):
    """
    Grant access to ATTENDEE, ORGANIZER, or ADMIN.
    Use on order/ticket endpoints (all authenticated users can buy tickets).
    """
    message = "You must be logged in to perform this action."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


# ── Object-level permissions ───────────────────────────────────────────────────

class IsEventOrganizer(BasePermission):
    """
    Object-level permission: user must be an ORGANIZER or ADMIN, AND
    the event must belong to one of their active organizations.

    Designed for EventViewSet with OrgScopedMixin.
    OrgScopedMixin scopes the queryset (non-member org → 404 before this fires).
    This class is the belt-and-suspenders 403 check.

    Example:
        def get_permissions(self):
            if self.action in ("partial_update", "publish", "cancel"):
                return [IsAuthenticated(), IsEventOrganizer()]
    """
    message = "You do not have organizer access to this event's organization."

    def has_permission(self, request, view):
        role = getattr(request.user, "role", None)
        return bool(
            request.user
            and request.user.is_authenticated
            and role in (ORGANIZER_ROLE, ADMIN_ROLE)
        )

    def has_object_permission(self, request, view, obj):
        user = request.user

        if getattr(user, "role", None) == ADMIN_ROLE:
            return True  # admins bypass object check

        # obj is an Event instance; check its org FK.
        return str(obj.org_id) in _user_org_ids(user)


class IsOrgMember(BasePermission):
    """
    User must have an active Membership in the organization identified
    in the URL kwarg (org_id or pk).

    Use on organization-scoped endpoints:
        GET /api/v1/orgs/{org_id}/members/
    """
    message = "You are not a member of this organization."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False

        if getattr(request.user, "role", None) == ADMIN_ROLE:
            return True

        # Try common URL kwarg names for the org PK.
        org_id = (
            view.kwargs.get("org_id")
            or view.kwargs.get("pk")
            or view.kwargs.get("id")
        )
        if not org_id:
            return False

        return request.user.membership_set.filter(
            org_id=org_id,
            org__is_active=True,
        ).exists()


class IsOwnerOrReadOnly(BasePermission):
    """
    Generic ownership check:
      - Safe methods (GET, HEAD, OPTIONS): always allowed.
      - Unsafe methods: only if obj.<owner_field>_id == request.user.pk.

    Override `owner_field` on the view for different FK names:
        permission_classes = [IsOwnerOrReadOnly]
        owner_field = "attendee"     # checks obj.attendee_id
    """
    owner_field = "owner"

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True

        field = getattr(view, "owner_field", self.owner_field)
        owner_id = getattr(obj, f"{field}_id", None)
        return owner_id == request.user.pk


class IsOrgOwnerOrManager(BasePermission):
    """
    User must hold the OWNER or MANAGER role within the event's org.
    Used for sensitive org-level actions (delete org, add members).

    Membership.role choices (from Phase 1):
        OWNER   — full control
        MANAGER — create/edit events, manage tiers
        MEMBER  — view only
    """
    message = "You must be an Owner or Manager of this organization."

    ALLOWED_MEMBERSHIP_ROLES = {"OWNER", "MANAGER"}

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if getattr(request.user, "role", None) == ADMIN_ROLE:
            return True
        return True  # object-level check below is authoritative

    def has_object_permission(self, request, view, obj):
        user = request.user

        if getattr(user, "role", None) == ADMIN_ROLE:
            return True

        # obj can be an Org or any model with an `org_id` FK.
        org_id = getattr(obj, "org_id", None) or getattr(obj, "id", None)
        if not org_id:
            return False

        return user.membership_set.filter(
            org_id=org_id,
            org__is_active=True,
            role__in=self.ALLOWED_MEMBERSHIP_ROLES,
        ).exists()


class IsVerifiedUser(BasePermission):
    message = "Email Verification required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "is_verified", False)
        )


class IsOrgOwnerOrAdmin(BasePermission):
    message = "Only the organization owner or a platform Admin can perform this action."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if getattr(user, "role", None) == ADMIN_ROLE:
            return True
        return obj.owner_id == user.id