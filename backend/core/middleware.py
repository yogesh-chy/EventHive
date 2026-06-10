"""
core/middleware.py  ·  PHASE 1

Two lightweight middleware classes:

  1. RequestIDMiddleware
     Injects a unique request ID into every request and response.
     The ID is propagated through logs so a single request can be
     traced across all log lines (including Celery tasks).

  2. StructuredRequestLogMiddleware
     Logs every request/response in a machine-parseable format
     (JSON via structlog or plain key=value). Includes:
     - method, path, status, duration_ms
     - request_id (from RequestIDMiddleware)
     - user_id (if authenticated)

Predicted problems addressed:
──────────────────────────────
1.  Without a request ID, correlating a user-reported error to a
    specific log line is guesswork. The ID is returned in the
    X-Request-ID response header so clients can report it.

2.  Middleware calling process_request after process_response in the
    wrong order — MIDDLEWARE ordering in settings matters. Both classes
    use the modern __call__ style (not the old process_* methods), which
    is middleware-order-safe.

3.  RequestID from client header accepted blindly — attacker could inject
    a crafted ID. Header is validated: if it's not 8–64 safe characters
    it's discarded and a new ID is generated.

4.  Logging response bodies would leak PII — we log only method, path,
    status, and duration. No request/response body ever logged.

5.  500 errors logged at ERROR level; 4xx at WARNING; 2xx/3xx at INFO.

Add to settings:
    MIDDLEWARE = [
        "core.middleware.RequestIDMiddleware",       # must be first
        "core.middleware.StructuredRequestLogMiddleware",
        ...
    ]
"""

import logging
import re
import time
import uuid

from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

# Thread-local storage so the request ID is accessible from anywhere
# in the call stack (e.g., Celery task spawned during the request).
import threading
_local = threading.local()

REQUEST_ID_HEADER = "X-Request-ID"
# Only accept safe alphanumeric + hyphen/underscore IDs from clients.
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9\-_]{8,64}$")


def get_current_request_id() -> str | None:
    """Return the request ID for the current thread. Usable from anywhere."""
    return getattr(_local, "request_id", None)


# ── RequestIDMiddleware ───────────────────────────────────────────────────────

class RequestIDMiddleware:
    """
    Assigns a unique ID to every request.

    Priority:
      1. Accept X-Request-ID from trusted upstream (load balancer / API gateway)
         only if the value passes the safe-character check.
      2. Generate a new UUIDv4 otherwise.

    The ID is stored in:
      - request.id                 → available to all views and middleware
      - threading.local().request_id → available to Celery tasks, signals, etc.
      - X-Request-ID response header → returned to the client
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = self._resolve_request_id(request)
        request.id = request_id
        _local.request_id = request_id

        response = self.get_response(request)

        response[REQUEST_ID_HEADER] = request_id
        # Clean up thread-local after response to avoid leaks in threaded servers.
        _local.request_id = None
        return response

    @staticmethod
    def _resolve_request_id(request) -> str:
        incoming = request.META.get(
            "HTTP_X_REQUEST_ID",
            request.META.get("HTTP_X_CORRELATION_ID", ""),
        )
        if incoming and _SAFE_ID_RE.match(incoming):
            return incoming
        return uuid.uuid4().hex


# ── StructuredRequestLogMiddleware ────────────────────────────────────────────

class StructuredRequestLogMiddleware:
    """
    Logs each request/response with structured key=value fields.

    Skips health-check endpoints to avoid log noise.
    """

    SKIP_PATHS = {"/health/", "/readyz/", "/livez/", "/favicon.ico"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in self.SKIP_PATHS:
            return self.get_response(request)

        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)

        status_code = response.status_code
        user_id = None
        if hasattr(request, "user") and request.user.is_authenticated:
            user_id = str(request.user.pk)

        log_data = {
            "request_id": getattr(request, "id", None),
            "method": request.method,
            "path": request.path,
            "status": status_code,
            "duration_ms": duration_ms,
            "user_id": user_id,
        }

        if status_code >= 500:
            logger.error("request_completed", extra=log_data)
        elif status_code >= 400:
            logger.warning("request_completed", extra=log_data)
        else:
            logger.info("request_completed", extra=log_data)

        return response


# Backward compatibility middlewares and audit helpers
from django.conf import settings
from django.db import connection

_audit_context = threading.local()

def get_current_user():
    return getattr(_audit_context, "user", None)

def get_current_ip():
    return getattr(_audit_context, "ip_address", None)

def _get_client_ip(request) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        _audit_context.user = getattr(request, "user", None)
        _audit_context.ip_address = _get_client_ip(request)
        response = self.get_response(request)
        _audit_context.user = None
        _audit_context.ip_address = None
        return response


class QueryTimingMiddleware:
    SLOW_QUERY_MS = getattr(settings, "SLOW_QUERY_THRESHOLD_MS", 100)
    MAX_QUERIES = getattr(settings, "MAX_QUERIES_PER_REQUEST", 30)

    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        if not settings.DEBUG:
            return self.get_response(request)
        
        initial_queries = len(connection.queries)
        start = time.monotonic()
        response = self.get_response(request)
        elapsed_ms = (time.monotonic() - start) * 1000
        queries_fired = len(connection.queries) - initial_queries

        if queries_fired > self.MAX_QUERIES:
            logger.warning(
                "HIGH QUERY COUNT: %s %s → %d queries in %.1fms (N+1 smell?)",
                request.method,
                request.path,
                queries_fired,
                elapsed_ms,
            )
        else:
            for q in connection.queries[initial_queries:]:
                q_time_ms = float(q.get("time", 0)) * 1000
                if q_time_ms > self.SLOW_QUERY_MS:
                    logger.warning(
                        "SLOW QUERY (%.1fms): %s", q_time_ms, q["sql"][:200]
                    )

        return response