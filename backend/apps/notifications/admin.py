from django.contrib import admin

from .models import NotificationLog

@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = (
        "notification_type",
        "target_type",
        "target_id",
        "recipient_email",
        "status",
        "attempts",
        "created_at",
        "sent_at",
    )
    list_filter = ("notification_type", "status")
    search_fields = ("target_id", "recipient_email")
    readonly_fields = ("id", "created_at")
    ordering = ("-created_at",)
