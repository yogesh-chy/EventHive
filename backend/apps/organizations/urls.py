from django.urls import path
from apps.organizations.views import (
    InviteMemberView,
    MemberListView,
    OrganizationDetailView,
    OrganizationListCreateView,
)

urlpatterns = [
    path("", OrganizationListCreateView.as_view(), name="org-list-create"),
    path("<uuid:org_id>/", OrganizationDetailView.as_view(), name="org-detail"),
    path("<uuid:org_id>/members/", MemberListView.as_view(), name="org-members"),
    path("<uuid:org_id>/invite/", InviteMemberView.as_view(), name="org-invite"),
]