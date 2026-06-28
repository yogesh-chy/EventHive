"""
Phase 5: services/search.py, and the Postgres trigger that maintains
Event.search_vector (apps/events/migrations/0002_search_vector_trigger_and_trigram.py).

Requires real PostgreSQL -- SearchQuery/SearchRank/TrigramSimilarity have
no SQLite equivalent, so these tests cannot run against the sqlite
fallback some of the other test files use.
"""
import pytest

from apps.events.models import Event, EventStatus
from services.search import search_events
from tests.factories import EventFactory, OrganizationFactory


@pytest.mark.django_db
class TestSearchVectorTrigger:
    """The bug this migration fixes: search_vector was never populated by
    anything before this phase, so every search silently returned zero
    results since Phase 2."""

    def test_search_vector_populated_on_create(self):
        event = EventFactory(title="Jazz Night Live", description="An evening of jazz")
        event.refresh_from_db()
        assert event.search_vector is not None

    def test_search_vector_updates_when_title_changes(self):
        event = EventFactory(title="Original Title")
        event.refresh_from_db()
        vector_before = event.search_vector

        event.title = "Completely Different Words"
        event.save(update_fields=["title"])
        event.refresh_from_db()

        assert event.search_vector != vector_before

    def test_search_vector_survives_bulk_update(self):
        """The whole reason this is a DB trigger and not a Django signal:
        signals never fire on .update(), bulk_create() does, etc."""
        event = EventFactory(title="Bulk Test Event")
        Event.objects.filter(id=event.id).update(title="Renamed Via Bulk Update")
        event.refresh_from_db()
        assert event.search_vector is not None
        # confirm it actually re-derived from the NEW title, not stale
        results = search_events(query_str="Renamed")
        assert event in list(results)


@pytest.mark.django_db
class TestSearchEvents:
    def test_finds_event_by_title_keyword(self):
        target = EventFactory(title="Tokyo Jazz Festival", description="Live music")
        other = EventFactory(title="Berlin Tech Conference", description="Talks and workshops")

        results = list(search_events(query_str="jazz"))

        assert target in results
        assert other not in results

    def test_only_returns_published_events(self):
        published = EventFactory(title="Open Mic Night", status=EventStatus.PUBLISHED)
        draft = EventFactory(title="Open Mic Rehearsal", status=EventStatus.DRAFT)

        results = list(search_events(query_str="open mic"))

        assert published in results
        assert draft not in results

    def test_empty_query_returns_all_published_events_ordered(self):
        EventFactory(title="Event One")
        EventFactory(title="Event Two")
        EventFactory(title="Draft Event", status=EventStatus.DRAFT)

        results = list(search_events(query_str=""))

        assert len(results) == 2
        assert all(e.status == EventStatus.PUBLISHED for e in results)

    def test_ranks_title_match_above_description_only_match(self):
        """setweight('A') on title vs 'C' on description -- a title hit
        should outrank a description-only hit for the same term."""
        title_match = EventFactory(
            title="Comedy Night Special", description="An evening out"
        )
        desc_only_match = EventFactory(
            title="Friday Social", description="Featuring a comedy night vibe"
        )

        results = list(search_events(query_str="comedy"))

        assert results[0].id == title_match.id

    def test_typo_falls_back_to_trigram_similarity(self):
        """No tsquery lexeme match for a misspelling -- the trigram
        fallback must still surface it."""
        event = EventFactory(title="Jazz Festival", city="San Francisco")

        results = list(search_events(query_str="jaz festval"))

        assert event in results

    def test_trigram_fallback_only_triggers_when_fulltext_finds_nothing(self):
        """A query that DOES match full-text should never fall through to
        the noisier trigram path."""
        exact = EventFactory(title="Rock Concert", city="Austin")
        unrelated = EventFactory(title="Cooking Class", city="Austin")

        results = list(search_events(query_str="rock"))

        assert exact in results
        assert unrelated not in results

    def test_completely_unrelated_query_returns_nothing(self):
        EventFactory(title="Jazz Festival", city="San Francisco")

        results = list(search_events(query_str="xyzabc123nonsense"))

        assert len(results) == 0

    def test_respects_pre_filtered_base_queryset(self):
        """Org-scoped search: the optional `queryset` param must be
        respected, not silently widened back to all events."""
        org_a = OrganizationFactory()
        org_b = OrganizationFactory()
        event_a = EventFactory(org=org_a, title="Shared Keyword Concert")
        EventFactory(org=org_b, title="Shared Keyword Concert")

        scoped = Event.objects.filter(org=org_a)
        results = list(search_events(query_str="keyword", queryset=scoped))

        assert results == [event_a]
