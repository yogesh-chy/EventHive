import uuid
from django.db import models
from django.utils import timezone

class SoftDeleteQuerySet(models.QuerySet):
    
    def delete(self):
        return self.update(is_delete=True, update_at=timezone.now())
    
    def hard_delete(self):
        return super().delete()

    def restore(self):
        return self.update(is_deleted=False, update_at=timezone.now())
    
    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)

class SoftDeleteManager(models.Manager):

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)
    
    def hard_delete(self):
        return self.get_queryset().hard_delete()
    
    def restore(self):
        return self.get_queryset().restore()
    
    def alive(self):
        return self.get_queryset().alive()
    
    def dead(self):
        return SoftDeleteQuerySet(self.model, using=self._db)
    
    def all_with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db)

class BaseModel(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    update_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False, db_index=True)

    objects = SoftDeleteManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"
    
    def delete(self, using=None, keep_parents=False):
        self.is_deleted = True
        self.update_at = timezone.now()
        self.save(update_fields=["is_deleted", "updated_at"])

    def hard_delete(self, using=None, keep_parents=False):
        super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        self.is_deleted = False
        self.update_at = timezone.now()
        self.save(update_fields=["is_deleted", "update_at"])
    
    def __repr__(self):
        return f"<{self.__class__.__name__} id={self.id}>"