import pytest
from django.urls import reverse
from django.core import mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User
from tests.factories import UserFactory

@pytest.fixture
def api_client():
    return APIClient()

@pytest.mark.django_db
class TestPasswordReset:

    def test_password_reset_request_sends_email(self, api_client):
        user = UserFactory(email="reset@example.com")
        url = reverse("auth-password-reset")
        payload = {"email": "reset@example.com"}

        response = api_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True
        assert "sent" in response.data["data"]["message"]

        # Verify email was sent
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert email.to == ["reset@example.com"]
        assert "Reset your EventHive password" in email.subject
        assert "uid=" in email.body
        assert "token=" in email.body

    def test_password_reset_request_non_existent_email(self, api_client):
        # Should return 200 to prevent user enumeration
        url = reverse("auth-password-reset")
        payload = {"email": "nobody@example.com"}

        response = api_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert len(mail.outbox) == 0

    def test_password_reset_confirm_success(self, api_client):
        user = UserFactory(email="confirm@example.com")
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        url = reverse("auth-password-reset-confirm")
        payload = {
            "uid": uid,
            "token": token,
            "new_password": "NewSecurePassword123!"
        }

        response = api_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True
        assert "successfully" in response.data["data"]["message"]

        # Verify we can login with the new password
        login_url = reverse("auth-login")
        login_payload = {
            "email": "confirm@example.com",
            "password": "NewSecurePassword123!"
        }
        login_response = api_client.post(login_url, login_payload, format="json")
        assert login_response.status_code == status.HTTP_200_OK
        assert "access" in login_response.data["data"]

    def test_password_reset_confirm_invalid_token(self, api_client):
        user = UserFactory(email="badtoken@example.com")
        uid = urlsafe_base64_encode(force_bytes(user.pk))

        url = reverse("auth-password-reset-confirm")
        payload = {
            "uid": uid,
            "token": "invalid-token",
            "new_password": "NewSecurePassword123!"
        }

        response = api_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["success"] is False
