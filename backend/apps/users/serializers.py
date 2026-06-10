import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from .models import User, EmailVerificationToken

# ------Helpers-----
def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()

def _generate_and_store_verification_token(user: User) -> str:
    raw_token = secrets.token_urlsafe(32)
    hashed = _hash_token(raw_token)
    expires_at = timezone.now() + timedelta(hours=getattr(settings, "EMAIL_VERIFICATION_EXPIRY_HOURS", 24))

    EmailVerificationToken.objects.filter(user=user).delete()
    EmailVerificationToken.objects.create(user=user, token_hash=hashed, expires_at=expires_at)

    return raw_token

# ------Registeration-----
class UserRegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=255)
    password = serializers.CharField(min_length=8, write_only=True, style={"input_type":"password"})
    full_name = serializers.CharField(max_length=255)
    role = serializers.ChoiceField(choices=[User.Role.ORGANIZER, User.Role.ATTENDEE],default=User.Role.ATTENDEE,help_text="ADMIN accounts cannot be self-registered.")

    def validate_email(self, value:str) -> str:
        normalized = value.lower().strip()
        if User.objects.filter(email=normalized).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return normalized
    
    def validate_password(self, value:str) -> str:
        if value.isdigit():
            raise serializers.ValidationError("Password cannot be entirely numeric.")
        return value
    
    def create(self, validated_data: dict) -> User:
        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            full_name=validated_data.get("full_name", ""),
            role=validated_data.get("role", User.Role.ATTENDEE)
        )
        raw_token = _generate_and_store_verification_token(user)
        self._send_verification_email(user, raw_token)
        return user
    
    def _send_verification_email(self, user: User, raw_token:str):
        verification_url = (f"{settings.FRONTEND_URL}/auth/verify-email?token={raw_token}")
        subject = "Verify your EventHive email address"
        message = (
            f"Hello! {user.full_name}, \n\n"
            f"Please verify your email by visiting:\n{verification_url}\n\n"
            f"This link expires in 24 hours.\n\nEventHive Team"
        )
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False
        )

# ------Email Verification-----
class EmailVerifySerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True)

    def validate_token(self, value:str):
        hashed = _hash_token(value.strip())
        try:
            verification = EmailVerificationToken.objects.select_related("user").get(token_hash=hashed)
        except EmailVerificationToken.DoesNotExist:
            raise serializers.ValidationError("Invalid or expired verification link.")
        
        if verification.user.is_verified:
            raise serializers.ValidationError("Email is already verified.")
        
        self.context["verification"] = verification
        return value
    
    def save(self) -> User:
        verification: EmailVerificationToken = self.context["verification"]
        user = verification.user
        user.is_verified = True
        user.save(update_fields=["is_verified"])
        return user
    

# ------Login-----

class LoginSerializer(TokenObtainPairSerializer):
    
    def validate(self, attrs: dict) -> dict:
        # Normalize email
        attrs[self.username_field] = attrs[self.username_field].lower().strip()
        
        data = super().validate(attrs)
        user: User = self.user

        if not user.is_active:
            raise serializers.ValidationError("This account has been suspended. Contact support.")
        if not user.is_verified:
            raise serializers.ValidationError("Please verify your email before logging in.")
        
        # Get IP Address
        ip = self.context["request"].META.get("REMOTE_ADDR", "")
        forwarded = self.context["request"].META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        
        user.record_login(ip)
        
        # Add extra data to the response (optional, as it's already in the token)
        data["user"] = {
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role
        }
        
        return data

    @classmethod
    def get_token(cls, user: User):
        token = super().get_token(user)
        token["email"] = user.email
        token["role"] = user.role
        token["full_name"] = user.full_name
        return token

# ------Profile-----
class UserProfileSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField(help_text="Presigned S3 URL (1hr expiry). Do not cache beyond expiry.")

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "role", "avatar_url", "is_verified", "last_login_at"]
        read_only_fields = ["id", "email", "role", "is_verified", "last_login_at"]

    def get_avatar_url(self, obj: User) -> str | None:
        if not obj.avatar:
            return None
        return None

class UserProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["full_name", "avatar"]

    def validate_full_name(self, value: str) -> str:
        return value.strip()


# ------Password Reset-----
class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.strip().lower()

    def save(self):
        email = self.validated_data["email"]
        try:
            user = User.objects.get(email=email, is_active=True)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = f"{settings.FRONTEND_URL}/auth/password-reset/confirm?uid={uid}&token={token}"
            
            subject = "Reset your EventHive password"
            message = (
                f"Hello {user.full_name},\n\n"
                f"You requested a password reset. Please click the link below to set a new password:\n{reset_url}\n\n"
                f"If you did not request this, please ignore this email.\n\nEventHive Team"
            )
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False
            )
        except User.DoesNotExist:
            pass


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(min_length=8, write_only=True)

    def validate(self, attrs):
        try:
            uid = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=uid, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({"token": "Invalid or expired password reset link."})

        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError({"token": "Invalid or expired password reset link."})

        attrs["user"] = user
        return attrs

    def save(self):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user