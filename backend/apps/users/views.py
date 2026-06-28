from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from .serializers import EmailVerifySerializer, LoginSerializer, UserProfileSerializer, UserProfileUpdateSerializer, UserRegisterSerializer, PasswordResetRequestSerializer, PasswordResetConfirmSerializer
from core.permissions import IsVerifiedUser

class RegisterView(APIView):

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        serializer = UserRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {
                "success":True, 
                "data":{
                    "message":(
                        "Register successful."
                        "Please check your email to verify your account."
                    ),
                    "email":user.email,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailView(APIView):

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailVerifySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {
                "success": True,
                "data": {
                    "message": "Email verified successfully. You can now log in.",
                    "email": user.email,
                },
            },
            status=status.HTTP_200_OK,
        )


class LoginView(APIView):

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request":request})
        serializer.is_valid(raise_exception=True)
        return Response(
            {"success": True, "data": serializer.validated_data},
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {
                    "success":False,
                    "error":[
                        {"field":"refresh", "message": "Refresh token is required."}
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception:
            pass
        return Response(
            {"success": True, "data": {"message": "Logged out successfully."}},
            status=status.HTTP_200_OK,
        )


class TokenRefreshExtendedView(TokenRefreshView):

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            return Response(
                {"success": True, "data": response.data},
                status=status.HTTP_200_OK,
            )
        return response


class UserMeView(APIView):

    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(
            {"success": True, "data": serializer.data},
            status=status.HTTP_200_OK,
        )
    
    def patch(self, request):
        serializer = UserProfileUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {
                "success": True,
                "data": UserProfileSerializer(request.user).data,
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def get_throttles(self):
        throttles = super().get_throttles()
        from core.throttles import PasswordResetEmailThrottle
        throttles.append(PasswordResetEmailThrottle())
        return throttles

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {
                "success": True,
                "data": {
                    "message": "If a matching account exists, a password reset link has been sent."
                }
            },
            status=status.HTTP_200_OK
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {
                "success": True,
                "data": {
                    "message": "Password has been reset successfully."
                }
            },
            status=status.HTTP_200_OK
        )