from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, EmailVerificatonToken

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    # The forms to add and change user instances
    list_display = ("email", "full_name", "role", "is_verified", "is_staff", "is_active")
    list_filter = ("role", "is_verified", "is_staff", "is_active")
    
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("full_name", "avatar")}),
        ("Permissions", {"fields": ("role", "is_verified", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "last_login_at", "last_login_ip")}),
    )
    
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "full_name", "role", "password"),
        }),
    )
    
    search_fields = ("email", "full_name")
    ordering = ("email",)
    filter_horizontal = ("groups", "user_permissions")

@admin.register(EmailVerificatonToken)
class EmailVerificationTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "expires_at", "is_expired")
    search_fields = ("user__email",)
    readonly_fields = ("created_at",)
