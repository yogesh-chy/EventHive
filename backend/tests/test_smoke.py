# import pytest
# from django.contrib.auth import get_user_model

# User = get_user_model()

# @pytest.mark.django_db
# def test_user_model_exists():
#     """
#     Smoke test to ensure the custom User model is registered correctly.
#     """
#     assert User is not None
#     assert User.objects.count() == 0

# def test_settings_loaded():
#     """
#     Smoke test to ensure settings are loaded.
#     """
#     from django.conf import settings
#     assert settings.SECRET_KEY is not None
