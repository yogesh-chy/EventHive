import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.events.models import Event, EventStatus, TicketTier
from tests.factories import (
    OrganizerFactory,
    OrganizationFactory,
    UserFactory,
    EventFactory,
    TicketTierFactory,
)

@pytest.fixture
def api_client():
    return APIClient()

@pytest.fixture
def attendee_client(api_client):
    user = UserFactory()
    api_client.force_authenticate(user=user)
    api_client._user = user
    return api_client

@pytest.fixture
def organizer_client(api_client):
    user = OrganizerFactory()
    api_client.force_authenticate(user=user)
    api_client._user = user
    return api_client

@pytest.mark.django_db
class TestEventAPI:

    def test_list_events_only_returns_published(self, api_client):
        # Create a published event and a draft event
        published_event = EventFactory(status=EventStatus.PUBLISHED)
        draft_event = EventFactory(status=EventStatus.DRAFT)

        url = reverse("event_list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data
        if isinstance(results, dict) and "results" in results:
            results = results["results"]

        slugs = [event["slug"] for event in results]
        assert published_event.slug in slugs
        assert draft_event.slug not in slugs

    def test_retrieve_published_event(self, api_client):
        event = EventFactory(status=EventStatus.PUBLISHED)
        url = reverse("event_detail", kwargs={"slug": event.slug})
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["slug"] == event.slug

    def test_retrieve_draft_event_fails_for_anonymous(self, api_client):
        event = EventFactory(status=EventStatus.DRAFT)
        url = reverse("event_detail", kwargs={"slug": event.slug})
        response = api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_event_success(self, organizer_client):
        org = OrganizationFactory(owner=organizer_client._user)

        url = reverse("event_list")
        payload = {
            "title": "Super Awesome Conference 2026",
            "description": "An amazing conference.",
            "venue": "San Francisco Hall",
            "city": "San Francisco",
            "country": "US",
            "start_datetime": "2026-07-09T09:00:00Z",
            "end_datetime": "2026-07-09T17:00:00Z",
            "total_capacity": 500,
            "org_id": str(org.id)
        }

        response = organizer_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["title"] == "Super Awesome Conference 2026"
        assert response.data["slug"] == "super-awesome-conference-2026"

        assert Event.objects.filter(slug="super-awesome-conference-2026").exists()

    def test_publish_event_success(self, organizer_client):
        org = OrganizationFactory(owner=organizer_client._user)
        event = EventFactory(org=org, status=EventStatus.DRAFT)
        TicketTierFactory(event=event, is_active=True)

        url = reverse("event_publish", kwargs={"slug": event.slug})
        response = organizer_client.post(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == EventStatus.PUBLISHED

        event.refresh_from_db()
        assert event.status == EventStatus.PUBLISHED

    def test_cancel_event_success(self, organizer_client):
        org = OrganizationFactory(owner=organizer_client._user)
        event = EventFactory(org=org, status=EventStatus.PUBLISHED)

        url = reverse("event_cancel", kwargs={"slug": event.slug})
        response = organizer_client.post(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == EventStatus.CANCELLED

        event.refresh_from_db()
        assert event.status == EventStatus.CANCELLED


@pytest.mark.django_db
class TestTicketTierAPI:

    def test_list_ticket_tiers(self, api_client):
        event = EventFactory(status=EventStatus.PUBLISHED)
        TicketTierFactory(event=event, price=10.00)
        TicketTierFactory(event=event, price=20.00)

        url = reverse("tier_list", kwargs={"event_slug": event.slug})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2
        assert float(response.data[0]["price"]) == 10.00
        assert float(response.data[1]["price"]) == 20.00

    def test_create_ticket_tier(self, organizer_client):
        org = OrganizationFactory(owner=organizer_client._user)
        event = EventFactory(org=org, status=EventStatus.DRAFT)

        url = reverse("tier_list", kwargs={"event_slug": event.slug})
        payload = {
            "name": "Early Bird",
            "price": "15.00",
            "quantity": 100,
        }

        response = organizer_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "Early Bird"
        assert float(response.data["price"]) == 15.00

        assert TicketTier.objects.filter(event=event, name="Early Bird").exists()
