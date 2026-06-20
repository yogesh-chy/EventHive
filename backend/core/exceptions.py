import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler

logger = logging.getLogger(__name__)


# ---- Normalisation helpers ----
def _flatten_errors(detail: Any, attr: str | None = None) -> list[dict]:
    """
    Recursively flatten DRF's nested error structures into a flat list:
    [{"code": str, "detail": str, "attr": str | null}]

    Handles:
      - Single ErrorDetail
      - List of ErrorDetails
      - Dict of {field: [ErrorDetails]}  (serializer field errors)
      - Non-string scalar (should not occur, but handled defensively)
    """
    errors = []

    if isinstance(detail, dict):
        for field, value in detail.items():
            errors.extend(_flatten_errors(value, attr=field))

    elif isinstance(detail, list):
        for item in detail:
            errors.extend(_flatten_errors(item, attr=attr))

    else:
        code = getattr(detail, "code", "error")
        errors.append({
            "code": code,
            "detail": str(detail),
            "attr": attr,
        })

    return errors


def _make_envelope(errors: list[dict]) -> dict:
    return {"success": False, "errors": errors}


# ---- Main handler ----
def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    """
    Drop-in replacement for DRF's default exception handler.
    All API error responses share the same JSON envelope.

    Settings:
        REST_FRAMEWORK["EXCEPTION_HANDLER"] = "core.exceptions.custom_exception_handler"
    """

    # Convert Django core exceptions to DRF equivalents so they pass
    # through the standard handler and get proper HTTP status codes.
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(detail=exc.message_dict if hasattr(exc, "message_dict") else exc.messages)

    if isinstance(exc, Http404):
        exc = APIException()
        exc.status_code = status.HTTP_404_NOT_FOUND
        exc.detail = "Not found."  # type: ignore[attr-defined]

    if isinstance(exc, DjangoPermissionDenied):
        exc = APIException()
        exc.status_code = status.HTTP_403_FORBIDDEN
        exc.detail = "Permission denied."  # type: ignore[attr-defined]

    # Let DRF set the response for known exceptions (4xx).
    response = drf_default_handler(exc, context)

    if response is None:
        # Unhandled exception — this will become a 500.
        # Log with full traceback; return a safe response.
        logger.exception(
            "Unhandled exception in %s.%s",
            context.get("view").__class__.__name__ if context.get("view") else "unknown",
            context.get("request").method if context.get("request") else "unknown",
        )
        return Response(
            _make_envelope([{"code": "server_error", "detail": "An unexpected error occurred.", "attr": None}]),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Normalise the response data into our envelope.
    errors = _flatten_errors(response.data)
    response.data = _make_envelope(errors)
    return response


# ---- Custom application exceptions ----
class EventHiveAPIException(APIException):
    """
    Base class for all EventHive-specific exceptions.
    Subclass this to add domain-specific error codes.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "eventhive_error"
    default_detail = "A business rule was violated."


class InvalidStatusTransitionError(EventHiveAPIException):
    """Raised when a status transition is not allowed by the state machine."""
    status_code = status.HTTP_409_CONFLICT
    default_code = "invalid_status_transition"
    default_detail = "This status transition is not permitted."


class InsufficientInventoryError(EventHiveAPIException):
    """Raised when a ticket purchase exceeds available inventory."""
    status_code = status.HTTP_409_CONFLICT
    default_code = "insufficient_inventory"
    default_detail = "Insufficient ticket inventory for this request."


class SeatAlreadyReservedError(EventHiveAPIException):
    """Raised when a seat lock already exists (Phase 3 — checkout flow)."""
    status_code = status.HTTP_409_CONFLICT
    default_code = "seat_already_reserved"
    default_detail = "The requested seats are temporarily reserved by another session."


class OrderExpiredError(EventHiveAPIException):
    # Raised when a pending order's hold time has lapsed (Phase 3 — checkout flow).
    status_code    = status.HTTP_410_GONE
    default_code   = "order_expired"
    default_detail = "This order has expired. Please start a new checkout."


class OrderAlreadyConfirmedError(EventHiveAPIException):
    # Raised when attempting to cancel an already-confirmed order (Phase 3).
    status_code    = status.HTTP_409_CONFLICT
    default_code   = "order_already_confirmed"
    default_detail = "This order has already been confirmed and cannot be cancelled directly."


class PaymentFailedError(EventHiveAPIException):
    status_code    = status.HTTP_402_PAYMENT_REQUIRED
    default_code   = "payment_failed"
    default_detail = "Payment could not be processed. Please try again or use a different payment method."


class RefundFailedError(EventHiveAPIException):
    status_code    = status.HTTP_502_BAD_GATEWAY
    default_code   = "refund_failed"
    default_detail = "The refund could not be processed by the payment provider. Please try again or contact support."



class OrganizationAccessDeniedError(EventHiveAPIException):
    """Raised when a user attempts to access data outside their org scope."""
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "org_access_denied"
    default_detail = "You do not have access to this organization."


class PublishValidationError(EventHiveAPIException):
    """Raised when an event fails publish pre-condition checks."""
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "publish_validation_failed"
    default_detail = "Event does not meet the requirements for publishing."


# Backward compatibility exceptions used in organizations services
class ResourceNotFound(EventHiveAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "not_found"
    default_detail = "The requested resource was not found."


class ConflictError(EventHiveAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"
    default_detail = "A conflict occurred."

