import logging
import threading
import time

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

# Thread-local storage for request context (used by AuditLog helpers)
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
        # Set context before the view runs
        _audit_context.user = getattr(request, "user", None)
        _audit_context.ip_address = _get_client_ip(request)

        response = self.get_response(request)

        # Clear context after response to avoid stale data on thread reuse
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

        elapsed_ms = (time.monotonic() -start)*1000
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