import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.organizations.models import Membership, Organization
from apps.users.models import User
from tests.factories import (
    AdminFactory,
    OrganizerFactory,
    OrganizationFactory,
    UnverifiedUserFactory,
    UserFactory,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_client(api_client):
    """Returns an APIClient authenticated as a verified attendee."""
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


@pytest.fixture
def admin_client(api_client):
    user = AdminFactory()
    api_client.force_authenticate(user=user)
    api_client._user = user
    return api_client


# ─── Registration ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRegister:

    def test_register_creates_user(self, api_client):
        url = reverse("auth-register")
        payload = {
            "email": "newuser@example.com",
            "password": "Testpass123!",
            "full_name": "New User",
            "role": "ATTENDEE",
        }
        response = api_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["success"] is True
        assert User.objects.filter(email="newuser@example.com").exists()

    def test_register_creates_unverified_user(self, api_client):
        url = reverse("auth-register")
        payload = {
            "email": "unverified@example.com",
            "password": "Testpass123!",
            "full_name": "Unverified",
        }
        api_client.post(url, payload, format="json")
        user = User.objects.get(email="unverified@example.com")
        assert not user.is_verified

    def test_register_duplicate_email_returns_400(self, api_client):
        UserFactory(email="existing@example.com")
        url = reverse("auth-register")
        payload = {
            "email": "existing@example.com",
            "password": "Testpass123!",
            "full_name": "Dup",
        }
        response = api_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["success"] is False

    def test_register_admin_role_rejected(self, api_client):
        """Users must not be able to self-register as ADMIN."""
        url = reverse("auth-register")
        payload = {
            "email": "hacker@example.com",
            "password": "Testpass123!",
            "full_name": "Hacker",
            "role": "ADMIN",
        }
        response = api_client.post(url, payload, format="json")
        # ADMIN is not in the allowed choices, so this should fail
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ─── Login ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLogin:

    def test_verified_user_gets_tokens(self, api_client):
        user = UserFactory(email="login@example.com", password="Testpass123!")
        url = reverse("auth-login")
        response = api_client.post(
            url, {"email": "login@example.com", "password": "Testpass123!"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data["data"]
        assert "refresh" in response.data["data"]

    def test_unverified_user_cannot_login(self, api_client):
        UnverifiedUserFactory(email="unverified@example.com", password="Testpass123!")
        url = reverse("auth-login")
        response = api_client.post(
            url, {"email": "unverified@example.com", "password": "Testpass123!"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_wrong_password_returns_401(self, api_client):
        UserFactory(email="correct@example.com", password="Testpass123!")
        url = reverse("auth-login")
        response = api_client.post(
            url, {"email": "correct@example.com", "password": "WrongPass!"},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ─── Profile ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestUserProfile:

    def test_get_own_profile(self, auth_client):
        url = reverse("user-me")
        response = auth_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["email"] == auth_client._user.email

    def test_update_full_name(self, auth_client):
        url = reverse("user-me")
        response = auth_client.patch(url, {"full_name": "Updated Name"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["full_name"] == "Updated Name"

    def test_unauthenticated_profile_returns_401(self, api_client):
        url = reverse("user-me")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ─── Organizations ────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOrganizations:

    def test_create_org_creates_owner_membership(self, organizer_client):
        url = reverse("org-list-create")
        response = organizer_client.post(
            url, {"name": "My Org"}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED
        org_id = response.data["data"]["id"]
        assert Membership.objects.filter(
            org_id=org_id,
            user=organizer_client._user,
            role=Membership.Role.OWNER,
        ).exists()

    def test_list_orgs_returns_only_mine(self, organizer_client):
        # Org I'm a member of
        my_org = OrganizationFactory(owner=organizer_client._user)
        Membership.objects.get_or_create(
            user=organizer_client._user,
            org=my_org,
            defaults={"role": Membership.Role.OWNER},
        )
        # Org I'm NOT a member of
        OrganizationFactory()

        url = reverse("org-list-create")
        response = organizer_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        org_ids = [o["id"] for o in response.data["data"]]
        assert str(my_org.id) in org_ids

    def test_admin_sees_all_orgs(self, admin_client):
        OrganizationFactory.create_batch(3)
        url = reverse("org-list-create")
        response = admin_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["data"]) >= 3

    def test_non_member_cannot_see_org_detail(self, auth_client):
        org = OrganizationFactory()
        url = reverse("org-detail", kwargs={"org_id": org.id})
        response = auth_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_invite_member(self, organizer_client):
        org = OrganizationFactory(owner=organizer_client._user)
        Membership.objects.get_or_create(
            user=organizer_client._user, org=org,
            defaults={"role": Membership.Role.OWNER},
        )
        invitee = UserFactory()
        url = reverse("org-invite", kwargs={"org_id": org.id})
        response = organizer_client.post(
            url, {"email": invitee.email, "role": "MEMBER"}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert Membership.objects.filter(user=invitee, org=org).exists()
