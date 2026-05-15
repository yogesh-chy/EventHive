import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils import timezone

from .managers import UserManager

class User(AbstractBaseUser, PermissionsMixin):

    class Role(models.TextChoices):
        ADMIN = "ADMIN","admin"
        ORGANIZER = "ORGANIZER", "organizer"
        ATTENDEE = "ATTENDEE", "attendee"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True, max_length=255)
    full_name = models.CharField(max_length=255, blank=True)
    avatar = models.CharField(max_length=512, blank=True, help_text="S3 object key — NOT a full URL. Generate presigned URL in serializer.")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ATTENDEE, db_index=True)
    is_active = models.BooleanField(default=True, help_text="Designates whether this user should be treated as active.")
    is_staff = models.BooleanField(default=False, help_text="Django admin access (not the same as ADMIN role).")
    is_verified = models.BooleanField(default=False, db_index=True, help_text="Email address has been verified via the verification link.")

    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]
    class Meta:
        db_table = 'users'
        managed = True
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["role", "is_active"])
        ]

    def __str__(self):
        return self.email
    
    def get_full_name(self):
        return self.full_name or self.email
    
    def get_short_name(self):
        return self.full_name.split()[0] if self.full_name else self.email
    
    def record_login(self, ip_address:str):
        self.last_login_ip = ip_address
        self.last_login_at = timezone.now()
        self.save(update_fields=["last_login_ip", "last_login_at"])
    
    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN
    
    @property
    def is_organizer(self) -> bool:
        return self.role == self.Role.ORGANIZER
    
    @property
    def is_attende(self) -> bool:
        return self.role == self.Role.ATTENDEE
    
class EmailVerificatonToken(models.Model):

    import hashlib

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User,on_delete=models.CASCADE, related_name="email_verification_token")
    token_hash = models.CharField(max_length=64, help_text="SHA-256 hash of the raw token sent to the user.")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'email_verification_tokens'

    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at
    
    def __str__(self):
        return f"EmailVerificationToken(user={self.user_id})"