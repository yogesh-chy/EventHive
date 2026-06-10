"""
core/pagination.py  ·  PHASE 2

Pagination classes for EventHive.

  EventCursorPagination   — for public event list (fast, stable)
  StandardPagePagination  — for admin / export endpoints (jump-to-page)
  TierPagePagination      — for ticket tier lists under an event

Predicted problems addressed:
──────────────────────────────
1.  Offset pagination on large tables is O(offset):
      SELECT * FROM events ORDER BY start_datetime LIMIT 20 OFFSET 10000
    gets slower with every page. At 50K events, page 500 is unusably slow.
    → CursorPagination issues a WHERE clause on an indexed column instead:
      SELECT * FROM events WHERE start_datetime < <cursor> LIMIT 20
    Every page takes the same time regardless of position.

2.  Non-deterministic ordering causes duplicate or missing rows on page
    boundaries if two rows share the same ordering value:
    → ordering = ("-start_datetime", "id") — UUID id breaks all ties,
      ensuring the cursor always points to an exact unique row.

3.  Client passes page_size=999999 to fetch all records in one request
    and bypass pagination entirely:
    → max_page_size = 50 hard cap. DRF enforces this silently.

4.  CursorPagination doesn't expose total count (by design — counting
    a filtered table is expensive). Some clients need a count:
    → StandardPagePagination (used for admin/exports) does include count.

5.  Cursor value leaking internal DB field values:
    → DRF CursorPagination base-64-encodes the cursor value and adds
      a reverse flag. Field names/values are not directly visible.
"""

from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.response import Response


# ── CursorPagination (public list endpoints) ──────────────────────────────────

class EventCursorPagination(CursorPagination):
    """
    Cursor-based pagination for the public event list.

    Clients receive opaque `next` / `previous` URLs — no page numbers.
    Suitable for infinite-scroll UIs and mobile apps.

    Default: 20 events per page. Max: 50.
    """
    page_size             = 20
    max_page_size         = 50
    page_size_query_param = "page_size"
    # Two-field ordering: primary sort on start_datetime (indexed),
    # tie-broken by UUID id so the cursor is always unique.
    ordering              = ("-start_datetime", "id")

    def get_paginated_response(self, data):
        return Response({
            "next":     self.get_next_link(),
            "previous": self.get_previous_link(),
            "results":  data,
        })

    def get_paginated_response_schema(self, schema):
        """OpenAPI schema for drf-spectacular."""
        return {
            "type": "object",
            "properties": {
                "next":     {"type": "string", "nullable": True},
                "previous": {"type": "string", "nullable": True},
                "results":  schema,
            },
        }


# ── PageNumberPagination (admin / export endpoints) ───────────────────────────

class StandardPagePagination(PageNumberPagination):
    """
    Page-number pagination for admin endpoints and data exports
    where jump-to-page-N behaviour is needed.

    Includes total count and total_pages in the response envelope.
    Not suitable for large public lists — use EventCursorPagination there.

    Default: 25 per page. Max: 100.
    """
    page_size             = 25
    max_page_size         = 100
    page_size_query_param = "page_size"
    page_query_param      = "page"

    def get_paginated_response(self, data):
        return Response({
            "count":       self.page.paginator.count,
            "total_pages": self.page.paginator.num_pages,
            "next":        self.get_next_link(),
            "previous":    self.get_previous_link(),
            "results":     data,
        })

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "count":       {"type": "integer"},
                "total_pages": {"type": "integer"},
                "next":        {"type": "string", "nullable": True},
                "previous":    {"type": "string", "nullable": True},
                "results":     schema,
            },
        }


# ── Small list pagination (ticket tiers, org members, etc.) ───────────────────

class SmallPagePagination(PageNumberPagination):
    """
    Tiny page size for nested resources (tiers, members, orders).
    These lists are small by nature; pagination is mostly for consistency.

    Default: 50 per page. Max: 50 (no override allowed).
    """
    page_size             = 50
    max_page_size         = 50
    page_size_query_param = None  # clients cannot change the page size

    def get_paginated_response(self, data):
        return Response({
            "count":    self.page.paginator.count,
            "next":     self.get_next_link(),
            "previous": self.get_previous_link(),
            "results":  data,
        })