from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.models import Membership
from apps.organizations.serializers import InviteMemberSerializer, MembershipSerializer, OrgnaizationCreateSerializer, OrganizationSerializer, OrganizationUpdateSerializer
from apps.organizations.services import OrganizationService
from core.permissions import IsVerifiedUser

class OrganizationListCreateView(APIView):

    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def get(self, request):
        orgs = OrganizationService.get_user_organizations(request.user)
        orgs = orgs.prefetch_related("membership_set")
        serializer = OrganizationSerializer(orgs, many=True)
        return Response({"success":True, "data":serializer.data}, status=status.HTTP_200_OK)
    
    def post(self, request):
        serializer = OrgnaizationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org = OrganizationService.create_organization(owner=request.user, name=serializer.validated_data["name"])
        return Response({"success":True, "data":OrganizationSerializer(org).data}, status=status.HTTP_201_CREATED)
    

class OrganizationDetailView(APIView):

    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def _get_org(self, org_id: str):
        return OrganizationService.get_org_or_404(org_id, self.request.user)

    def get(self, request, org_id):
        org = self._get_org(org_id)
        serializer = OrganizationSerializer(org)
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)

    def patch(self, request, org_id):
        org = self._get_org(org_id)

        if not (request.user.is_admin or org.owner_id == request.user.id):
            raise PermissionError("Only the organization owner or platform Admin can update organization details.")
        
        serializer = OrganizationUpdateSerializer(org, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"success": True, "data": OrganizationSerializer(org).data}, status=status.HTTP_200_OK)

class MemberListView(APIView):

    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def get(self, request, org_id):
        org = OrganizationService.get_org_or_404(org_id, request.user)

        if not (request.user.is_admin or org.owner_id == request.user.id):
            raise PermissionError("only Owner or Admin can view members.")
        
        membership = (Membership.objects.filter(org=org).select_related("user").order_by("joined_at"))
        serializer = MembershipSerializer(membership, many=True)
        return Response({"success": True, "data": serializer.data},status=status.HTTP_200_OK)
    

class InviteMemberView(APIView):
     
     permission_classes = [IsAuthenticated, IsVerifiedUser]

     def post(self, request, org_id):
        org = OrganizationService.get_org_or_404(org_id, request.user)

        if not (request.user.is_admin or org.owner_id == request.user.id):
             raise PermissionError("Only the owner or Admin can invite members.")
        
        serializer = InviteMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        membership = OrganizationService.invite_member(
            org=org,
            inviter=request.user,
            invite_email=serializer.validated_data["email"],
            role=serializer.validated_data["role"],
        )

        return Response({"success": True, "data": MembershipSerializer(membership).data}, status=status.HTTP_201_CREATED)
