
from rest_framework.pagination import CursorPagination as _CursorPagination
from rest_framework.response import Response


class CursorPagination(_CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")

    def get_paginated_response(self, data):
        return Response(
            {
                "success": True,
                "pagination": {
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link(),
                    "page_size": self.page_size,
                },
                "data": data,
            }
        )

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "pagination": {
                    "type": "object",
                    "properties": {
                        "next": {"type": "string", "nullable": True},
                        "previous": {"type": "string", "nullable": True},
                        "page_size": {"type": "integer"},
                    },
                },
                "data": schema,
            },
        }
