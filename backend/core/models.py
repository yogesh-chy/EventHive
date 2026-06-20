import uuid

from django.conf import settings
from django.db import models


# ---- Managers ----
class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet that adds a soft_delete() helper and filters out deleted rows."""

    def soft_delete(self):
        """Mark all matched rows as deleted instead of issuing a SQL DELETE."""
        return self.update(is_deleted=True)

    def alive(self):
        """Convenience: return only non-deleted rows."""
        return self.filter(is_deleted=False)

    def deleted(self):
        """Return only soft-deleted rows (admin / audit use)."""
        return self.filter(is_deleted=True)


class SoftDeleteManager(models.Manager):
    """
    Default manager: excludes soft-deleted rows from every query.

    Usage in models:
        objects = SoftDeleteManager()   ← default, hides deleted rows
        all_objects = AllObjectsManager()  ← includes deleted rows
    """

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)

    def soft_delete(self):
        return self.get_queryset().soft_delete()


class AllObjectsManager(models.Manager):
    """
    Bypass manager for admin, migrations, and audit views.
    Returns ALL rows including soft-deleted ones.
    """

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)


# ---- Abstract base model ----
class BaseModel(models.Model):
    """
    Abstract model providing:
      - UUID primary key
      - created_at / updated_at timestamps
      - created_by optional user FK
      - is_deleted soft-delete flag
      - SoftDeleteManager as default + AllObjectsManager escape hatch

    All EventHive models inherit from this.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Globally unique identifier (UUIDv4). Set in Python before INSERT.",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="UTC timestamp of row creation. Never writable.",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="UTC timestamp of last update. Managed by Django ORM.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",  # no reverse accessor — avoids name conflicts
        help_text="User who created this record. Null for system-generated rows.",
    )

    is_deleted = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Soft-delete flag. Rows with is_deleted=True are hidden from default queries.",
    )

    #  Managers 
    objects = SoftDeleteManager()       # default: hides deleted rows
    all_objects = AllObjectsManager()   # explicit: includes deleted rows

    class Meta:
        abstract = True
        # Concrete subclasses inherit ordering=[] (no default ordering)
        # so they can declare their own without conflicts.

    #  Soft delete helpers 

    def soft_delete(self, save: bool = True) -> None:
        """
        Mark this instance as deleted.
        Does NOT call Django's delete() — no CASCADE, no signals from deletion.
        """
        self.is_deleted = True
        if save:
            self.save(update_fields=["is_deleted", "updated_at"])

    def restore(self, save: bool = True) -> None:
        """Un-delete this instance."""
        self.is_deleted = False
        if save:
            self.save(update_fields=["is_deleted", "updated_at"])

    #  Dunder helpers 

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id}>"