import uuid

from django.db import models
from django.utils.text import slugify

from core.models import BaseModel

class Organization(BaseModel):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True, db_index=True, help_text="URL-safe identifier. Auto-generated from name.")
    owner = models.ForeignKey("users.User", on_delete=models.PROTECT, related_name="owned_organization")
    logo = models.CharField(max_length=512, blank=True, help_text="S3 object key for organization logo.")
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "organizations"
        verbose_name = "Organization"
        verbose_name_plural = "Organizations"
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["owner", "is_active"]),
        ]

    def __str__(self):
        return f"{self.name}"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)
    
    def _generate_unique_slug(self) -> str:
        base_slug = slugify(self.name)[:90]
        if not Organization.objects.filter(slug=base_slug).exists():
            return base_slug
        suffix = str(uuid.uuid4()).replace("-","")[:8]
        return f"{base_slug}-{suffix}"


class Membership(models.Model):

    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        MANAGER = "MANAGER", "Manager"
        MEMBER = "MEMBER", "Member"
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="membership_set")
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="membership_set")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER, db_index=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "membership"
        unique_together = [("user","org")]
        indexes = [
            models.Index(fields=["org", "role"]),
            models.Index(fields=["user", "org"]),
        ]

    def __str__(self):
        return f"{self.user_id} @ {self.org_id} [{self.role}]"    