import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from core.models import BaseModel

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin, BaseModel):
    email = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    
    # Roles
    ADMIN = 'ADMIN'
    ORGANIZER = 'ORGANIZER'
    ATTENDEE = 'ATTENDEE'
    ROLE_CHOICES = [
        (ADMIN, 'Admin'),
        (ORGANIZER, 'Organizer'),
        (ATTENDEE, 'Attendee'),
    ]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ATTENDEE)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    def __str__(self):
        return self.email
