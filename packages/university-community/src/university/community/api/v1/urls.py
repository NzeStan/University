from __future__ import annotations

from django.urls import path

from university.community.api.v1 import views

app_name = "community"

C = "communities/<uuid:community_id>/"
M = f"{C}members/<uuid:user_id>/"

urlpatterns = [
    path("communities/", views.CommunityListCreateView.as_view(), name="community-list"),
    path("communities/join-with-code/", views.JoinWithCodeView.as_view(), name="join-with-code"),
    path(C, views.CommunityDetailView.as_view(), name="community-detail"),
    path(f"{C}official/", views.OfficialView.as_view(), name="community-official"),
    path(f"{C}join/", views.JoinView.as_view(), name="community-join"),
    path(f"{C}leave/", views.LeaveView.as_view(), name="community-leave"),
    path(f"{C}members/", views.MemberListView.as_view(), name="member-list"),
    path(f"{C}requests/", views.RequestListView.as_view(), name="request-list"),
    path(f"{C}bans/", views.BanListView.as_view(), name="ban-list"),
    path(M, views.member_action("role").as_view(), name="member-role"),
    path(f"{M}approve/", views.member_action("approve").as_view(), name="member-approve"),
    path(f"{M}decline/", views.member_action("decline").as_view(), name="member-decline"),
    path(f"{M}remove/", views.member_action("remove").as_view(), name="member-remove"),
    path(f"{M}ban/", views.member_action("ban").as_view(), name="member-ban"),
    path(f"{M}unban/", views.member_action("unban").as_view(), name="member-unban"),
    path(f"{C}transfer-ownership/", views.TransferView.as_view(), name="transfer-ownership"),
    path(f"{C}invitations/", views.InvitationView.as_view(), name="invitation-create"),
    path(
        f"{C}invitations/accept/",
        type("AcceptInvitationView", (views.InvitationResponseView,), {"accept": True}).as_view(),
        name="invitation-accept",
    ),
    path(
        f"{C}invitations/decline/",
        type("DeclineInvitationView", (views.InvitationResponseView,), {"accept": False}).as_view(),
        name="invitation-decline",
    ),
    path(f"{C}invite-links/", views.InviteLinkView.as_view(), name="invite-link-create"),
    path(f"{C}invite-links/<uuid:link_id>/", views.InviteLinkDetailView.as_view(), name="invite-link-detail"),
    path("me/communities/", views.MyCommunitiesView.as_view(), name="my-communities"),
    path("me/community-invitations/", views.MyInvitationsView.as_view(), name="my-invitations"),
]
