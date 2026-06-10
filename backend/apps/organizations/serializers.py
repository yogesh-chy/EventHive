from rest_framework import serializers

from apps.organizations.models import Membership, Organization
from apps.users.serializers import UserProfileSerializer

class MembershipSerializer(serializers.ModelSerializer):
    user = UserProfileSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user", "role", "joined_at"]
        read_only_fields = ["id","user","joined_at"]

class OrganizationSerializer(serializers.ModelSerializer):
    owner = UserProfileSerializer(read_only=True)
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "owner", "logo", "is_active", "member_count", "created_at", "updated_at"]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]

    def get_member_count(self, obj: Organization) -> int:
        
        if hasattr(obj,"_prefetched_objects_cache") and "membership_set" in obj._prefetched_objects_cache:
            return len(obj._prefetched_objects_cache["membership_set"])
        return obj.membership_set.count()

class OrgnaizationCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length = 255, min_length=2)

    def validate_name(self, value: str) -> str:
        return value.strip()
    
class OrganizationUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["name", "is_active"]

    def validate_name(self, value: str) -> str:
        return value.strip()

class InviteMemberSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=[Membership.Role.MANAGER, Membership.Role.MEMBER], default=Membership.Role.MEMBER)

    def validate_email(self, value: str) -> str:
        return value.lower().strip()
