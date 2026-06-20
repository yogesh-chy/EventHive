"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              EventHive — core_all_phases.py                                ║
║   Complete core layer for Phase 1 + Phase 2 + Phase 3 in one file          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Split into individual modules when placing in the project:                ║
║                                                                              ║
║  core/models.py       ← SECTION 1  (Phase 1)                               ║
║  core/exceptions.py   ← SECTION 2  (Phase 1 + Phase 3 additions)           ║
║  core/middleware.py   ← SECTION 3  (Phase 1)                               ║
║  core/cache.py        ← SECTION 4  (Phase 2 + Phase 3 additions)           ║
║  core/mixins.py       ← SECTION 5  (Phase 2 + Phase 3 additions)           ║
║  core/pagination.py   ← SECTION 6  (Phase 2)                               ║
║  core/permissions.py  ← SECTION 7  (Phase 2 + Phase 3 additions)           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import hashlib
import json
import logging
import re
import threading
import time
import uuid as _uuid_mod

from django.conf import settings
from django.db import models


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — core/models.py                                         PHASE 1
# ══════════════════════════════════════════════════════════════════════════════
"""
Abstract base model inherited by every EventHive model.

Predicted problems addressed:
  1. Sequential ID enumeration attacks → UUID PK generated in Python before INSERT.
  2. Hard deletes losing audit history → soft-delete flag + SoftDeleteManager.
  3. Timezone-naive timestamps → auto_now_add/auto_now always UTC (USE_TZ=True).
  4. created_by FK on user delete → SET_NULL keeps the record.
  5. SoftDeleteManager hiding records unexpectedly → AllObjectsManager
     provided as explicit escape hatch for admin and migrations.
"""


class SoftDeleteQuerySet(models.QuerySet):
    def soft_delete(self):
        return self.update(is_deleted=True)

    def alive(self):
        return self.filter(is_deleted=False)

    def deleted(self):
        return self.filter(is_deleted=True)


class SoftDeleteManager(models.Manager):
    """Default manager — hides soft-deleted rows from every query."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)

    def soft_delete(self):
        return self.get_queryset().soft_delete()


class AllObjectsManager(models.Manager):
    """Bypass manager for admin / migrations / audit. Returns ALL rows."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)


class BaseModel(models.Model):
    """
    Abstract model: UUID PK, timestamps, soft-delete, created_by.
    All EventHive models inherit from this.
    """

    id = models.UUIDField(
        primary_key=True,
        default=_uuid_mod.uuid4,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    is_deleted = models.BooleanField(default=False, db_index=True)

    objects     = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def soft_delete(self, save: bool = True) -> None:
        self.is_deleted = True
        if save:
            self.save(update_fields=["is_deleted", "updated_at"])

    def restore(self, save: bool = True) -> None:
        self.is_deleted = False
        if save:
            self.save(update_fields=["is_deleted", "updated_at"])

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id}>"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — core/exceptions.py                         PHASE 1 + 3 additions
# ══════════════════════════════════════════════════════════════════════════════
"""
Custom DRF exception handler + all domain exceptions.

All API errors → {"errors": [{"code": "...", "detail": "...", "attr": "..."}]}

Wire up in settings:
  REST_FRAMEWORK = {"EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler"}

Predicted problems addressed:
  1. DRF's inconsistent error formats → recursive _flatten_errors() normalises all.
  2. Unhandled 500s leaking stack traces → caught, logged, safe envelope returned.
  3. Django Http404 / PermissionDenied bypassing DRF handler → converted first.
"""

from rest_framework import status as _drf_status
from rest_framework.exceptions import APIException, ValidationError as _DRFValidationError
from rest_framework.response import Response as _DRFResponse
from rest_framework.views import exception_handler as _drf_default_handler
from django.core.exceptions import (
    PermissionDenied as _DjangoPermissionDenied,
    ValidationError as _DjangoValidationError,
)
from django.http import Http404 as _Http404

_exc_logger = logging.getLogger(__name__)


def _flatten_errors(detail, attr=None):
    errors = []
    if isinstance(detail, dict):
        for field, value in detail.items():
            errors.extend(_flatten_errors(value, attr=field))
    elif isinstance(detail, list):
        for item in detail:
            errors.extend(_flatten_errors(item, attr=attr))
    else:
        errors.append({
            "code":   getattr(detail, "code", "error"),
            "detail": str(detail),
            "attr":   attr,
        })
    return errors


def custom_exception_handler(exc, context):
    """
    DRF EXCEPTION_HANDLER = "core.exceptions.custom_exception_handler"
    """
    if isinstance(exc, _DjangoValidationError):
        exc = _DRFValidationError(
            detail=exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        )
    if isinstance(exc, _Http404):
        exc = APIException(); exc.status_code = 404; exc.detail = "Not found."
    if isinstance(exc, _DjangoPermissionDenied):
        exc = APIException(); exc.status_code = 403; exc.detail = "Permission denied."

    response = _drf_default_handler(exc, context)
    if response is None:
        _exc_logger.exception(
            "Unhandled exception in view=%s method=%s",
            context.get("view").__class__.__name__ if context.get("view") else "unknown",
            context.get("request").method if context.get("request") else "unknown",
        )
        return _DRFResponse(
            {"errors": [{"code": "server_error", "detail": "An unexpected error occurred.", "attr": None}]},
            status=500,
        )

    response.data = {"errors": _flatten_errors(response.data)}
    return response


# ── Domain exceptions ──────────────────────────────────────────────────────────

class EventHiveAPIException(APIException):
    status_code  = _drf_status.HTTP_400_BAD_REQUEST
    default_code = "eventhive_error"


class InvalidStatusTransitionError(EventHiveAPIException):
    status_code    = _drf_status.HTTP_409_CONFLICT
    default_code   = "invalid_status_transition"
    default_detail = "This status transition is not permitted."


class InsufficientInventoryError(EventHiveAPIException):   # Phase 3
    status_code    = _drf_status.HTTP_409_CONFLICT
    default_code   = "insufficient_inventory"
    default_detail = "Insufficient ticket inventory for this request."


class SeatAlreadyReservedError(EventHiveAPIException):     # Phase 3
    status_code    = _drf_status.HTTP_409_CONFLICT
    default_code   = "seat_already_reserved"
    default_detail = "These seats are temporarily reserved by another session."


class OrderExpiredError(EventHiveAPIException):            # Phase 3
    status_code    = _drf_status.HTTP_410_GONE
    default_code   = "order_expired"
    default_detail = "This order has expired. Please start a new checkout."


class OrderAlreadyConfirmedError(EventHiveAPIException):   # Phase 3
    status_code    = _drf_status.HTTP_409_CONFLICT
    default_code   = "order_already_confirmed"
    default_detail = "This order has already been confirmed and cannot be cancelled directly."


class PaymentFailedError(EventHiveAPIException):           # Phase 3 — Payments re-alignment
    status_code    = _drf_status.HTTP_402_PAYMENT_REQUIRED
    default_code   = "payment_failed"
    default_detail = "Payment could not be processed. Please try again or use a different payment method."


class RefundFailedError(EventHiveAPIException):            # Phase 3 — Payments re-alignment
    status_code    = _drf_status.HTTP_502_BAD_GATEWAY
    default_code   = "refund_failed"
    default_detail = "The refund could not be processed by the payment provider. Please try again or contact support."


class PublishValidationError(EventHiveAPIException):
    status_code    = _drf_status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code   = "publish_validation_failed"
    default_detail = "Event does not meet the requirements for publishing."


class OrganizationAccessDeniedError(EventHiveAPIException):
    status_code    = _drf_status.HTTP_403_FORBIDDEN
    default_code   = "org_access_denied"
    default_detail = "You do not have access to this organization."


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — core/middleware.py                                      PHASE 1
# ══════════════════════════════════════════════════════════════════════════════
"""
RequestIDMiddleware              — injects unique X-Request-ID per request.
StructuredRequestLogMiddleware   — structured JSON log per request/response.

Add to MIDDLEWARE (RequestIDMiddleware MUST be first):
  "core.middleware.RequestIDMiddleware",
  "core.middleware.StructuredRequestLogMiddleware",

Predicted problems addressed:
  1. No way to trace a user error to a log line → X-Request-ID returned in header.
  2. Malicious X-Request-ID injection → validated against safe-char regex.
  3. Health-check paths flooding logs → SKIP_PATHS set excludes them.
  4. PII in logs → only method, path, status, duration logged, never bodies.
"""

_mw_logger  = logging.getLogger("core.middleware")
_local      = threading.local()
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9\-_]{8,64}$")


def get_current_request_id() -> str | None:
    return getattr(_local, "request_id", None)


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id        = self._resolve(request)
        request.id        = request_id
        _local.request_id = request_id
        response                 = self.get_response(request)
        response["X-Request-ID"] = request_id
        _local.request_id        = None
        return response

    @staticmethod
    def _resolve(request) -> str:
        incoming = request.META.get(
            "HTTP_X_REQUEST_ID",
            request.META.get("HTTP_X_CORRELATION_ID", ""),
        )
        if incoming and _SAFE_ID_RE.match(incoming):
            return incoming
        return _uuid_mod.uuid4().hex


class StructuredRequestLogMiddleware:
    SKIP_PATHS = {"/health/", "/readyz/", "/livez/", "/favicon.ico"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in self.SKIP_PATHS:
            return self.get_response(request)

        t0       = time.monotonic()
        response = self.get_response(request)
        dur_ms   = round((time.monotonic() - t0) * 1000, 2)
        code     = response.status_code
        user_id  = str(request.user.pk) if (
            hasattr(request, "user") and request.user.is_authenticated
        ) else None

        extra = dict(
            request_id=getattr(request, "id", None),
            method=request.method,
            path=request.path,
            status=code,
            duration_ms=dur_ms,
            user_id=user_id,
        )

        if code >= 500:
            _mw_logger.error("request_completed", extra=extra)
        elif code >= 400:
            _mw_logger.warning("request_completed", extra=extra)
        else:
            _mw_logger.info("request_completed", extra=extra)

        return response


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — core/cache.py                              PHASE 2 + 3 additions
# ══════════════════════════════════════════════════════════════════════════════
"""
Centralised cache key builders and invalidation helpers.

Namespace schema:
  eventhive:event:detail:<slug>               Phase 2
  eventhive:event:list:<hash>                 Phase 2
  eventhive:event:search:<hash>:<page>        Phase 2
  eventhive:org:detail:<org_id>               Phase 2
  eventhive:seat:lock:<tier_id>:<user_id>     Phase 3
  eventhive:order:detail:<order_id>           Phase 3

Predicted problems addressed:
  1. delete_pattern() only on django-redis → try/except AttributeError.
  2. Cache key collisions between domains → strict "eventhive:<domain>:" prefix.
  3. Query-param order affecting list key → sort_keys=True before hashing.
  4. Seat lock released too early → explicit release on confirm/cancel.
  5. Stale order cache after status change → invalidate_order_cache() called
     from service on every transition.
"""

from django.core.cache import cache as _cache

_cache_logger = logging.getLogger("core.cache")

# ── TTLs ──────────────────────────────────────────────────────────────────────
EVENT_DETAIL_TTL = 300   # 5 min
EVENT_LIST_TTL   = 120   # 2 min
EVENT_SEARCH_TTL = 120   # 2 min
SEAT_LOCK_TTL    = 600   # 10 min  Phase 3
ORDER_DETAIL_TTL = 60    # 1 min   Phase 3


def event_detail_key(slug: str) -> str:
    return f"eventhive:event:detail:{slug}"


def event_list_key(query_params: dict) -> str:
    param_str  = json.dumps(query_params, sort_keys=True, default=str)
    param_hash = hashlib.md5(param_str.encode(), usedforsecurity=False).hexdigest()
    return f"eventhive:event:list:{param_hash}"


def event_search_key(query: str, page=1) -> str:
    q_hash = hashlib.md5(query.lower().encode(), usedforsecurity=False).hexdigest()
    return f"eventhive:event:search:{q_hash}:{page}"


def org_detail_key(org_id: str) -> str:
    return f"eventhive:org:detail:{org_id}"


# Phase 3 keys ─────────────────────────────────────────────────────────────────

def seat_lock_key(tier_id: str, user_id: str) -> str:
    return f"eventhive:seat:lock:{tier_id}:{user_id}"


def order_detail_key(order_id: str) -> str:
    return f"eventhive:order:detail:{order_id}"


def acquire_seat_lock(tier_id: str, user_id: str, quantity: int) -> bool:
    """set(nx=True) — atomic; returns True if acquired, False if already held."""
    key      = seat_lock_key(str(tier_id), str(user_id))
    acquired = _cache.set(key, str(quantity), SEAT_LOCK_TTL, nx=True)
    _cache_logger.debug("seat_lock acquire key=%s acquired=%s", key, acquired)
    return bool(acquired)


def release_seat_lock(tier_id: str, user_id: str) -> None:
    _cache.delete(seat_lock_key(str(tier_id), str(user_id)))


def get_seat_lock_quantity(tier_id: str, user_id: str) -> int | None:
    value = _cache.get(seat_lock_key(str(tier_id), str(user_id)))
    return int(value) if value is not None else None


# Invalidation ─────────────────────────────────────────────────────────────────

def invalidate_event_cache(slug: str) -> None:
    _cache.delete(event_detail_key(slug))
    try:
        _cache.delete_pattern("eventhive:event:list:*")
        _cache.delete_pattern("eventhive:event:search:*")
    except AttributeError:
        _cache_logger.debug("delete_pattern not supported; list/search expire via TTL.")


def invalidate_org_cache(org_id: str) -> None:
    _cache.delete(org_detail_key(str(org_id)))


def invalidate_order_cache(order_id: str) -> None:
    _cache.delete(order_detail_key(str(order_id)))


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — core/mixins.py                             PHASE 2 + 3 additions
# ══════════════════════════════════════════════════════════════════════════════
"""
OrgScopedMixin       — multi-tenancy queryset enforcement.
AuditLogMixin        — write AuditLog entry after state-changing requests.
AttendeeOrderMixin   — Phase 3: scope order queryset to request.user.

Predicted problems addressed:
  1. Inconsistent tenancy enforcement → single apply_org_scope() method.
  2. Membership DB query per-request → cached in _cached_org_ids per view instance.
  3. Admin bypass must be explicit → ADMIN_ROLE check at top of apply_org_scope().
  4. AuditLog failure crashing a write → bare try/except in _write_audit().
  5. Attendee seeing other users' orders → AttendeeOrderMixin always filters
     by attendee=request.user; ADMIN sees all.
"""

_mixin_logger = logging.getLogger("core.mixins")
_ADMIN_ROLE   = "ADMIN"


class OrgScopedMixin:
    _cached_org_ids = None

    def _get_user_org_ids(self) -> list:
        if self._cached_org_ids is None:
            self._cached_org_ids = list(
                self.request.user.membership_set.filter(
                    org__is_active=True,
                ).values_list("org_id", flat=True)
            )
        return self._cached_org_ids

    def apply_org_scope(self, queryset):
        user = self.request.user
        if getattr(user, "role", None) == _ADMIN_ROLE:
            return queryset
        org_ids = self._get_user_org_ids()
        if not org_ids:
            return queryset.none()
        return queryset.filter(org_id__in=org_ids)

    def assert_org_access(self, org_id) -> None:
        from rest_framework.exceptions import PermissionDenied
        user = self.request.user
        if getattr(user, "role", None) == _ADMIN_ROLE:
            return
        if str(org_id) not in {str(i) for i in self._get_user_org_ids()}:
            raise PermissionDenied("You do not have access to this organization.")

    def get_org_from_url(self, org_id):
        from apps.organizations.models import Organization
        from rest_framework.exceptions import NotFound
        self.assert_org_access(org_id)
        try:
            return Organization.objects.get(pk=org_id, is_active=True)
        except Organization.DoesNotExist:
            raise NotFound("Organization not found.")


class AuditLogMixin:
    audit_action: str = "OBJECT"

    def perform_create(self, serializer):
        instance = serializer.save()
        self._write_audit(instance, f"{self.audit_action}_CREATED")
        return instance

    def perform_update(self, serializer):
        instance = serializer.save()
        self._write_audit(instance, f"{self.audit_action}_UPDATED")
        return instance

    def _write_audit(self, instance, action: str) -> None:
        try:
            from apps.audit.services import write_audit_log
            write_audit_log(actor=self.request.user, action=action,
                            entity=instance, request=self.request)
        except Exception:
            _mixin_logger.exception(
                "AuditLog write failed. action=%s — business op NOT rolled back.", action
            )


class AttendeeOrderMixin:               # Phase 3
    """Scope order queryset to request.user. Admins see all."""

    def apply_attendee_scope(self, queryset):
        user = self.request.user
        if getattr(user, "role", None) == _ADMIN_ROLE:
            return queryset
        return queryset.filter(attendee=user)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — core/pagination.py                                     PHASE 2
# ══════════════════════════════════════════════════════════════════════════════
"""
EventCursorPagination   — public event list (O(1) any page depth).
StandardPagePagination  — admin / exports (count, jump-to-page).
SmallPagePagination     — nested resources (tiers, items, members).

Predicted problems addressed:
  1. Offset pagination O(offset) → CursorPagination uses indexed WHERE clause.
  2. Ties at page boundary → ordering=("-start_datetime","id") always unique.
  3. Client requesting unlimited rows → max_page_size hard cap enforced by DRF.
"""

from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.response import Response as _PaginationResponse


class EventCursorPagination(CursorPagination):
    page_size             = 20
    max_page_size         = 50
    page_size_query_param = "page_size"
    ordering              = ("-start_datetime", "id")

    def get_paginated_response(self, data):
        return _PaginationResponse({
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": data,
        })


class StandardPagePagination(PageNumberPagination):
    page_size             = 25
    max_page_size         = 100
    page_size_query_param = "page_size"
    page_query_param      = "page"

    def get_paginated_response(self, data):
        return _PaginationResponse({
            "count":       self.page.paginator.count,
            "total_pages": self.page.paginator.num_pages,
            "next":        self.get_next_link(),
            "previous":    self.get_previous_link(),
            "results":     data,
        })


class SmallPagePagination(PageNumberPagination):
    page_size             = 50
    max_page_size         = 50
    page_size_query_param = None  # clients cannot override

    def get_paginated_response(self, data):
        return _PaginationResponse({
            "count":    self.page.paginator.count,
            "next":     self.get_next_link(),
            "previous": self.get_previous_link(),
            "results":  data,
        })


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — core/permissions.py                        PHASE 2 + 3 additions
# ══════════════════════════════════════════════════════════════════════════════
"""
All custom DRF permission classes.

Role hierarchy (User.role):
  ADMIN      → bypasses all org/object restrictions
  ORGANIZER  → creates/manages events
  ATTENDEE   → purchases tickets

Predicted problems addressed:
  1. AnonymousUser has no .role → getattr(user, "role", None) everywhere.
  2. Organizer patching another org's event → IsEventOrganizer checks
     has_object_permission() against the event's org FK.
  3. Inactive org members retaining access → filter includes org__is_active=True.
  4. Attendee accessing another user's order → IsOrderOwner checks
     order.attendee_id == request.user.pk.
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS as _SAFE_METHODS

ADMIN_ROLE     = "ADMIN"
ORGANIZER_ROLE = "ORGANIZER"
ATTENDEE_ROLE  = "ATTENDEE"


def _user_org_ids(user) -> set:
    return {
        str(pk) for pk in user.membership_set.filter(
            org__is_active=True,
        ).values_list("org_id", flat=True)
    }


class IsAdminUser(BasePermission):
    message = "You must be a platform administrator to perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and getattr(request.user, "role", None) == ADMIN_ROLE
        )


class IsOrganizer(BasePermission):
    message = "You must be an organizer to perform this action."

    def has_permission(self, request, view):
        role = getattr(request.user, "role", None)
        return bool(
            request.user and request.user.is_authenticated
            and role in (ORGANIZER_ROLE, ADMIN_ROLE)
        )


class IsEventOrganizer(BasePermission):
    """Two layers: OrgScopedMixin (404) + this class (403)."""
    message = "You do not have organizer access to this event's organization."

    def has_permission(self, request, view):
        role = getattr(request.user, "role", None)
        return bool(
            request.user and request.user.is_authenticated
            and role in (ORGANIZER_ROLE, ADMIN_ROLE)
        )

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, "role", None) == ADMIN_ROLE:
            return True
        return str(obj.org_id) in _user_org_ids(request.user)


class IsOrgMember(BasePermission):
    message = "You are not a member of this organization."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if getattr(request.user, "role", None) == ADMIN_ROLE:
            return True
        org_id = (
            view.kwargs.get("org_id")
            or view.kwargs.get("pk")
            or view.kwargs.get("id")
        )
        if not org_id:
            return False
        return request.user.membership_set.filter(
            org_id=org_id, org__is_active=True,
        ).exists()


class IsOrgOwnerOrManager(BasePermission):
    message = "You must be an Owner or Manager of this organization."
    ALLOWED_ROLES = {"OWNER", "MANAGER"}

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, "role", None) == ADMIN_ROLE:
            return True
        org_id = getattr(obj, "org_id", None) or getattr(obj, "id", None)
        if not org_id:
            return False
        return request.user.membership_set.filter(
            org_id=org_id, org__is_active=True, role__in=self.ALLOWED_ROLES,
        ).exists()


class IsOwnerOrReadOnly(BasePermission):
    owner_field = "owner"

    def has_object_permission(self, request, view, obj):
        if request.method in _SAFE_METHODS:
            return True
        field    = getattr(view, "owner_field", self.owner_field)
        owner_id = getattr(obj, f"{field}_id", None)
        return owner_id == request.user.pk


class IsOrderOwner(BasePermission):               # Phase 3
    """order.attendee_id must match request.user.pk. Admins bypass."""
    message = "You do not have access to this order."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, "role", None) == ADMIN_ROLE:
            return True
        return obj.attendee_id == request.user.pk
