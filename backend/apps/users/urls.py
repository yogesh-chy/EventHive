from django.urls import path
from .views import RegisterView, VerifyEmailView, LoginView, LogoutView, TokenRefreshExtendedView, UserMeView, PasswordResetRequestView, PasswordResetConfirmView

# Auth endpoints
auth_urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("verify-email/", VerifyEmailView.as_view(), name="auth-verify-email"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("token/refresh/", TokenRefreshExtendedView.as_view(), name="auth-token-refresh"),
    path("password/reset/", PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path("password/reset/confirm/", PasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"),
]

# User endpoints
user_urlpatterns = [
    path("me/", UserMeView.as_view(), name="user-me"),
]
# Combined urlpatterns
urlpatterns = auth_urlpatterns + user_urlpatterns
