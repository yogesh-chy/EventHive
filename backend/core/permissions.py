from rest_framework.permissions import BasePermission, SAFE_METHODS

class IsAdmin(BasePermission):
    
    def has_permission(self, request, view):
        return (request.user and request.user.is_authenticated and request.user.role == "ADMIN")


class IsOrganizer(BasePermission):

    def has_permission(self, request, view):
        return (request.user and request.user.is_authenticated and request.user.role in ("ADMIN", "ORANIZER"))


class IsVerifiedUser(BasePermission):
    message = "Email Verification required."

    def has_permission(self, request, view):
        return (request.user and request.user.is_authenticated and request.user.is_verified)


class IsOrgOwnerOrAdmin(BasePermission):
    message = "Only the organization owner or a platform Admin can perform this action."

    def has_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role == "ADMIN":
            return True
        return obj.owner_id == user.id


class IsOrgMemberOrReadOnly(BasePermission):

    def has_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True   
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role == "ADMIN":
            return True
        org = getattr(obj, "org", None) or getattr(obj, "organization", None)
        if org is None:
            return False
        return org.membership_set.filer(user=user).exists()