from django.contrib import admin

from .models import Membership, Organization


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    fields = ["user", "role", "joined_at"]
    readonly_fields = ["joined_at"]
    raw_id_fields = ["user"]


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "owner", "is_active", "member_count", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "slug", "owner__email"]
    readonly_fields = ["id", "slug", "created_at", "updated_at"]
    list_select_related = ["owner"]
    inlines = [MembershipInline]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(is_deleted=False)
            .select_related("owner")
            .prefetch_related("membership_set")
        )

    @admin.display(description="Members")
    def member_count(self, obj):
        if hasattr(obj, "_prefetched_objects_cache") and "membership_set" in obj._prefetched_objects_cache:
            return len(obj._prefetched_objects_cache["membership_set"])
        return obj.membership_set.count()


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "org", "role", "joined_at"]
    list_filter = ["role"]
    search_fields = ["user__email", "org__name"]
    list_select_related = ["user", "org"]
    readonly_fields = ["id", "joined_at"]
