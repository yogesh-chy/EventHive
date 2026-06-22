from django.db import IntegrityError, transaction

from apps.organizations.models import Membership, Organization
from apps.users.models import User
from core.exceptions import ConflictError, ResourceNotFound

class OrganizationService:

    @staticmethod
    @transaction.atomic
    def create_organization(owner: User, name: str, logo: str = "") -> Organization:
        try:
            org = Organization.objects.create(name=name.strip(), owner=owner, logo=logo)
        except IntegrityError:
            import uuid as _uuid
            safe_name = f"{name.strip()} {str(_uuid.uuid4())[:8]}"
            org = Organization.objects.create(name=safe_name, owner=owner, logo=logo)
        
        Membership.objects.create(user=owner, org=org, role=Membership.Role.OWNER)

        return org
    
    @staticmethod
    def get_user_organizations(user: User):
        
        if user.role == User.Role.ADMIN:
            return Organization.objects.filter(is_active=True).select_related("owner")
        org_ids = Membership.objects.filter(user=user).values_list("org_id", flat=True)

        return Organization.objects.filter(id__in=org_ids, is_active=True).select_related("owner")
    
    @staticmethod
    @transaction.atomic
    def invite_member(org: Organization, inviter: User, invite_email: str, role: str = Membership.Role.MEMBER) -> Membership:

        if invite_email.lower() == inviter.email.lower():
            raise ConflictError("You cannot invite yourself.")
        
        try:
            invitee = User.objects.get(email=invite_email.lower(), is_active=True)
        except User.DoesNotExist:
            raise ResourceNotFound(f"No active user found with email {invite_email}.")
        
        if Membership.objects.filter(user=invitee, org=org).exists():
            raise ConflictError(f"{invite_email} is already a member of {org.name}.")
        
        return Membership.objects.create(user=invitee, org=org, role=role)
    
    @staticmethod
    def get_org_or_404(org_id: str, user:User) -> Organization:

        try:
            org = Organization.objects.get(id=org_id, is_active=True)
        except Organization.DoesNotExist:
            raise ResourceNotFound("Organization not found.")
        
        if user.role == User.Role.ADMIN:
            return org
        
        if not Membership.objects.filter(user=user, org=org).exists():
            raise ResourceNotFound("Organization not found.")
        
        return org
