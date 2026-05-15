import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)

# ----Custom exceptions----

class EventHiveAPIException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "An error occured."
    default_code = "error"

class ResourceNotFound(EventHiveAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "The requested rescource was not found."
    default_code = "not_found"

class PermissionDenied(EventHiveAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "You do not have permission to perform this action."
    default_code = "permission_denied"

class ConflictError(EventHiveAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "An conflict occur."
    default_code = "conflict"

class UnprocessableEntity(EventHiveAPIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "Validation failed."
    default_code = "unprocessable_entity"

class ServiceUnavailable(EventHiveAPIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Service temporarily unavailable. Please try again."
    default_code = "service_unavailable"


# ----Response Envelope-----

def _build_error_response(errors: list, status_code: int) -> Response:
    return Response(
        {"success":False, "errors": errors},
        status=status_code
    )

def _normalize_drf_errors(detail) -> list:

    errors = []

    if isinstance(detail, dict):
        for field, messages in detail.items():
            if isinstance(messages, list):
                for msg in messages:
                    errors.append({"field": field, "message": str(msg)})
            elif isinstance(messages, dict):
                for sub_field, sub_msgs in messages.items():
                    for msg in (sub_msgs if isinstance(sub_msgs, list) else [sub_msgs]):
                        errors.append(
                            {"field": f"{field}.{sub_field}", "message": str(msg)}
                        )
            else:
                errors.append({"field": field, "message": str(messages)})

    elif isinstance(detail, list):
        for item in detail:
            if isinstance(item, dict):
                errors.extend(_normalize_drf_errors(item))
            else:
                errors.append({"field": "non_field_errors", "message": str(item)})
    else:
        errors.append({"field": "non_field_errors", "message": str(detail)})

    return errors


# ----Main Exception handler----

def custom_exception_handler(exc, context):

    response = drf_exception_handler(exc, context)

    if response is None and isinstance(exc, DjangoValidationError):
        messages = exc.messages if hasattr(exc, "messages") else [str(exc)]
        errors = [{"field": "non_field_errors", "message": m} for m in messages]
        return _build_error_response(errors, status.HTTP_400_BAD_REQUEST)

    if response is None:
        logger.exception(
            "Unhandled exception in view %s",
            context.get("view", "unknown"),
            exc_info=exc,
        )
        return _build_error_response(
            [{"field": "non_field_errors", "message": "An unexpected error occurred."}],
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, ValidationError):
        errors = _normalize_drf_errors(exc.detail)
    else:
        errors = [{"field": "non_field_errors", "message": str(exc.detail)}]

    return _build_error_response(errors, response.status_code)
