from typing import Optional

from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramSimilarity
from django.db.models import F, QuerySet

from apps.events.models import Event, EventStatus

TRIGRAM_SIMILARITY_THRESHOLD = 0.3

def search_events(*, query_str: str, queryset: Optional[QuerySet] = None) -> QuerySet:
    base_qs = queryset if queryset is not None else Event.objects.all()
    base_qs = base_qs.filter(status=EventStatus.PUBLISHED)

    query_str = (query_str or "").strip()
    if not query_str:
        return base_qs.order_by("-start_datetime", "id")
    
    search_query = SearchQuery(query_str, config="english")
    fts_qs = (
        base_qs.filter(search_vector=search_query)
        .annotate(rank=SearchRank(F("search_vector"), search_query))
        .order_by("-rank", "-start_datetime", "id")
    )
    if fts_qs.exists():
        return fts_qs
    
    return _trigram_fallback(base_qs, query_str)


def _trigram_fallback(base_qs: QuerySet, query_str: str) -> QuerySet:
    return (
        base_qs.annotate(
            similarity=(
                TrigramSimilarity("title", query_str) + TrigramSimilarity("city", query_str)
            )
        )
        .filter(similarity__gte=TRIGRAM_SIMILARITY_THRESHOLD)
        .order_by("-similarity", "-start_datetime", "id")
    )