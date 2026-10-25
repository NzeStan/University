"""university-community: privacy, membership, roles, invitations, integration."""

from __future__ import annotations

import pytest
from django.test import override_settings

from tests.audience.apps import MEMBERS
from university.audit.models import AuditLog
from university.community.models import Community, CommunityMembership
from university.core.audiences import is_member
from university.core.events import event_bus
from university.core.testing import create_user
from university.permissions.scopes import Scope
from university.permissions.services import assign_role, has_permission, scopes_with_permission

pytestmark = pytest.mark.django_db
BASE = "/api/v1/communities"


def create(client, name="Robotics Club", **extra):
    response = client.post(f"{BASE}/", {"name": name, **extra}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def join(client, community):
    return client.post(f"{BASE}/{community['id']}/join/")


# ---------------------------------------------------------------- creation
def test_create_and_owner(auth_client, user):
    community = create(auth_client(user), description="We build robots", rules=["Be kind"])
    assert community["slug"] == "robotics-club" and community["member_count"] == 1
    assert community["viewer"] == {"role": "owner", "status": "active"}
    second = create(auth_client(user), "Robotics Club")
    assert second["slug"] == "robotics-club-2"
    assert AuditLog.objects.filter(action="community.created").count() == 2


def test_creation_gates(auth_client, user, api_client):
    assert api_client.post(f"{BASE}/", {"name": "x"}, format="json").status_code == 401
    type(user).objects.filter(pk=user.pk).update(email_verified_at=None)
    assert auth_client(user).post(f"{BASE}/", {"name": "Club"}, format="json").status_code == 403
    verified = create_user("v@example.com", handle="verifiedone")
    with override_settings(UNIVERSITY={"COMMUNITY": {"CREATION_POLICY": "permission"}}):
        assert auth_client(verified).post(f"{BASE}/", {"name": "Club"}, format="json").status_code == 403
    with override_settings(UNIVERSITY={"COMMUNITY": {"MAX_OWNED_COMMUNITIES": 1}}):
        create(auth_client(verified), "One")
        assert (
            auth_client(verified).post(f"{BASE}/", {"name": "Two"}, format="json").json()["error"]["code"]
            == "ownership_limit"
        )
    assert auth_client(verified).post(f"{BASE}/", {"name": "x", "kind": "cult"}, format="json").status_code == 400


def test_linked_communities_require_audience(auth_client, user, other_user):
    client = auth_client(user)
    payload = {
        "name": "CSC 2026",
        "kind": "department",
        "parent_type": "institution",
        "parent_id": "inst-1",
        "requires_scope_membership": True,
    }
    assert client.post(f"{BASE}/", payload, format="json").status_code == 403
    MEMBERS[str(user.pk)] = [("institution", "inst-1")]
    community = create(client, **{k: v for k, v in payload.items() if k != "name"}, name="CSC 2026")
    assert community["parent"] == {"type": "institution", "id": "inst-1"}
    response = join(auth_client(other_user), community)
    assert response.status_code == 403 and response.json()["error"]["code"] == "not_audience_member"
    MEMBERS[str(other_user.pk)] = [("institution", "inst-1")]
    assert join(auth_client(other_user), community).json()["status"] == "active"


def test_official_recognition_needs_parent_manager(auth_client, user, superuser):
    MEMBERS[str(user.pk)] = [("institution", "inst-1")]
    community = create(auth_client(user), "Dept", parent_type="institution", parent_id="inst-1")
    # The owner cannot self-declare official.
    assert (
        auth_client(user).post(f"{BASE}/{community['id']}/official/", {"official": True}, format="json").status_code
        == 403
    )
    manager = create_user("mgr@example.com", handle="manager")
    assign_role(user=manager, role_key="community_manager", scope=Scope("institution", "inst-1"))
    assert (
        auth_client(manager)
        .post(f"{BASE}/{community['id']}/official/", {"official": True}, format="json")
        .json()["is_official"]
    )


# ----------------------------------------------------------------- privacy
def test_privacy_levels(auth_client, api_client, user, other_user):
    public = create(auth_client(user), "Open")
    restricted = create(auth_client(user), "Approval", privacy="restricted")
    private = create(auth_client(user), "Secret", privacy="private")
    listed = {c["name"] for c in api_client.get(f"{BASE}/").json()["results"]}
    assert listed == {"Open", "Approval"}
    assert api_client.get(f"{BASE}/{private['id']}/").status_code == 404
    grace = auth_client(other_user)
    assert join(grace, public).json()["status"] == "active"
    assert join(grace, restricted).json()["status"] == "pending"
    response = join(grace, private)
    assert response.status_code == 404  # existence not revealed
    assert grace.get(f"{BASE}/{private['id']}/members/").status_code == 404


def test_member_list_and_search(auth_client, api_client, user, other_user):
    community = create(auth_client(user), "Chess Society", description="Strategy")
    join(auth_client(other_user), community)
    members = api_client.get(f"{BASE}/{community['id']}/members/").json()["results"]
    assert {m["user"]["handle"] for m in members} == {"ada", "grace"}
    assert "email" not in str(members)
    assert api_client.get(f"{BASE}/?q=strategy").json()["count"] == 1


# ----------------------------------------------------------- join requests
def test_request_approval_flow(auth_client, user, other_user, third_user):
    community = create(auth_client(user), "Approval", privacy="restricted")
    join(auth_client(other_user), community)
    url = f"{BASE}/{community['id']}"
    assert auth_client(third_user).get(f"{url}/requests/").status_code == 403
    requests = auth_client(user).get(f"{url}/requests/").json()["results"]
    assert [r["user"]["handle"] for r in requests] == ["grace"]
    assert auth_client(user).post(f"{url}/members/{other_user.pk}/approve/").status_code == 204
    assert Community.objects.get(pk=community["id"]).member_count == 2
    assert auth_client(user).post(f"{url}/members/{other_user.pk}/approve/").status_code == 409


def test_leave_and_owner_must_transfer(auth_client, user, other_user):
    community = create(auth_client(user))
    join(auth_client(other_user), community)
    assert auth_client(other_user).post(f"{BASE}/{community['id']}/leave/").status_code == 204
    response = auth_client(user).post(f"{BASE}/{community['id']}/leave/")
    assert response.json()["error"]["code"] == "owner_must_transfer"


# ------------------------------------------------------------------- roles
@pytest.mark.security
def test_role_hierarchy(auth_client, user, other_user, third_user, fourth_user):
    community = create(auth_client(user))
    for u in (other_user, third_user, fourth_user):
        join(auth_client(u), community)
    url = f"{BASE}/{community['id']}/members"
    owner = auth_client(user)
    assert owner.patch(f"{url}/{other_user.pk}/", {"role": "admin"}, format="json").json()["role"] == "admin"
    admin = auth_client(other_user)
    # Admins can promote members to moderator, but not to admin (their own rank).
    assert admin.patch(f"{url}/{third_user.pk}/", {"role": "moderator"}, format="json").status_code == 200
    assert admin.patch(f"{url}/{fourth_user.pk}/", {"role": "admin"}, format="json").status_code == 403
    # Nobody acts on peers or superiors.
    assert admin.post(f"{url}/{user.pk}/remove/").status_code == 403
    assert (
        auth_client(third_user).post(f"{url}/{fourth_user.pk}/remove/").status_code == 403
    )  # moderators lack members.manage
    # Ownership is never granted through role changes.
    assert owner.patch(f"{url}/{other_user.pk}/", {"role": "owner"}, format="json").status_code == 400
    # Removal and bans.
    assert admin.post(f"{url}/{fourth_user.pk}/ban/", {"reason": "spam"}, format="json").status_code == 204
    assert join(auth_client(fourth_user), community).json()["error"]["code"] == "banned"
    assert [b["user"]["handle"] for b in admin.get(f"{BASE}/{community['id']}/bans/").json()["results"]] == ["tunde"]
    assert admin.post(f"{url}/{fourth_user.pk}/unban/").status_code == 204
    assert join(auth_client(fourth_user), community).json()["status"] == "active"
    assert AuditLog.objects.filter(action="community.role.changed").count() == 2


def test_transfer_ownership(auth_client, user, other_user):
    community = create(auth_client(user))
    join(auth_client(other_user), community)
    url = f"{BASE}/{community['id']}/transfer-ownership/"
    assert auth_client(other_user).post(url, {"user_id": str(other_user.pk)}, format="json").status_code == 403
    assert auth_client(user).post(url, {"user_id": str(other_user.pk)}, format="json").json()["role"] == "owner"
    roles = dict(CommunityMembership.objects.filter(community_id=community["id"]).values_list("user__handle", "role"))
    assert roles == {"ada": "admin", "grace": "owner"}
    assert auth_client(user).post(f"{BASE}/{community['id']}/leave/").status_code == 204


@pytest.mark.security
def test_settings_and_archive_need_manage(auth_client, user, other_user):
    community = create(auth_client(user))
    join(auth_client(other_user), community)
    url = f"{BASE}/{community['id']}/"
    assert auth_client(other_user).patch(url, {"name": "Hijacked"}, format="json").status_code == 403
    assert (
        auth_client(user).patch(url, {"name": "Renamed", "privacy": "restricted"}, format="json").json()["name"]
        == "Renamed"
    )
    assert auth_client(user).patch(url, {"member_count": 9999}, format="json").json()["member_count"] == 2
    assert auth_client(other_user).delete(url).status_code == 403
    assert auth_client(user).delete(url).status_code == 204
    assert Community.objects.get(pk=community["id"]).status == "archived"
    assert join(auth_client(create_user("late@example.com", handle="late")), community).status_code == 409


# ------------------------------------------------------------- invitations
def test_invitations_to_private_community(auth_client, user, other_user):
    community = create(auth_client(user), "Secret", privacy="private")
    url = f"{BASE}/{community['id']}"
    assert (
        auth_client(user).post(f"{url}/invitations/", {"user_id": str(other_user.pk)}, format="json").status_code == 201
    )
    grace = auth_client(other_user)
    assert [i["community"]["name"] for i in grace.get("/api/v1/me/community-invitations/").json()] == ["Secret"]
    assert grace.get(f"{url}/").status_code == 200  # invitees can see it
    assert grace.post(f"{url}/invitations/accept/").json()["status"] == "active"
    assert grace.post(f"{url}/invitations/accept/").status_code == 404


def test_invite_links(auth_client, user, other_user, third_user):
    community = create(auth_client(user), "Secret", privacy="private")
    created = auth_client(user).post(
        f"{BASE}/{community['id']}/invite-links/", {"expires_in_hours": 24, "max_uses": 1}, format="json"
    )
    code = created.json()["code"]
    assert (
        auth_client(other_user).post(f"{BASE}/join-with-code/", {"code": code}, format="json").json()["status"]
        == "active"
    )
    assert (
        auth_client(third_user).post(f"{BASE}/join-with-code/", {"code": code}, format="json").status_code == 404
    )  # used up
    assert auth_client(third_user).post(f"{BASE}/join-with-code/", {"code": "guess"}, format="json").status_code == 404
    from university.community.models import CommunityInviteLink

    assert code not in CommunityInviteLink.objects.get().code_hash  # stored hashed
    link_id = created.json()["id"]
    assert auth_client(other_user).delete(f"{BASE}/{community['id']}/invite-links/{link_id}/").status_code == 403
    assert auth_client(user).delete(f"{BASE}/{community['id']}/invite-links/{link_id}/").status_code == 204


# ------------------------------------------------------------- integration
def test_members_join_the_community_audience(auth_client, user, other_user):
    community = create(auth_client(user), "Restricted", privacy="restricted")
    join(auth_client(other_user), community)
    fresh = type(other_user).objects.get(pk=other_user.pk)
    assert not is_member(fresh, "community", community["id"])  # pending is not membership
    auth_client(user).post(f"{BASE}/{community['id']}/members/{other_user.pk}/approve/")
    fresh = type(other_user).objects.get(pk=other_user.pk)
    assert is_member(fresh, "community", community["id"])


def test_roles_grant_scoped_permissions_implicitly(auth_client, user, other_user, third_user):
    community = create(auth_client(user))
    join(auth_client(other_user), community)
    join(auth_client(third_user), community)
    auth_client(user).patch(f"{BASE}/{community['id']}/members/{other_user.pk}/", {"role": "moderator"}, format="json")
    scope = Scope("community", community["id"])
    mod = type(other_user).objects.get(pk=other_user.pk)
    member = type(third_user).objects.get(pk=third_user.pk)
    assert has_permission(mod, "moderation.cases.act", scope)
    assert not has_permission(mod, "moderation.appeals.decide", scope)  # admins and up
    assert not has_permission(mod, "moderation.cases.act", Scope("community", "other"))
    assert not has_permission(member, "moderation.cases.view", scope)
    assert scopes_with_permission(mod, "moderation.cases.view") == [scope]
    assert has_permission(type(user).objects.get(pk=user.pk), "community.manage", scope)


def test_parent_scope_managers_have_authority(auth_client, user, other_user):
    MEMBERS[str(user.pk)] = [("institution", "inst-1")]
    community = create(auth_client(user), "Dept", parent_type="institution", parent_id="inst-1")
    manager = create_user("mgr@example.com", handle="manager")
    assign_role(user=manager, role_key="community_manager", scope=Scope("institution", "inst-1"))
    assert (
        auth_client(manager).patch(f"{BASE}/{community['id']}/", {"description": "Official"}, format="json").status_code
        == 200
    )
    unrelated = create(auth_client(user), "Unlinked")
    assert (
        auth_client(manager).patch(f"{BASE}/{unrelated['id']}/", {"description": "x"}, format="json").status_code == 403
    )


def test_profile_shows_non_private_communities(auth_client, api_client, user):
    create(auth_client(user), "Visible")
    create(auth_client(user), "Hidden", privacy="private")
    extras = api_client.get(f"/api/v1/users/{user.pk}/").json()["extras"]
    assert [c["name"] for c in extras["communities"]] == ["Visible"]


def test_events(auth_client, user, other_user):
    seen = []
    event_bus.subscribe("community.*", seen.append)
    try:
        community = create(auth_client(user))
        join(auth_client(other_user), community)
    finally:
        event_bus.unsubscribe("community.*", seen.append)
    assert [e.name for e in seen] == ["community.created", "community.member.joined"]


def test_export_and_purge_with_succession(auth_client, user, other_user, third_user):
    from university.core.testing import PASSWORD
    from university.users.services import delete_account, purge_user

    community = create(auth_client(user))
    join(auth_client(other_user), community)
    join(auth_client(third_user), community)
    auth_client(user).patch(f"{BASE}/{community['id']}/members/{third_user.pk}/", {"role": "admin"}, format="json")
    lonely = create(auth_client(user), "Lonely")
    assert auth_client(user).get("/api/v1/me/export/").json()["communities"]
    delete_account(user, password=PASSWORD)
    purge_user(type(user).all_objects.get(pk=user.pk))
    owner = CommunityMembership.objects.get(community_id=community["id"], role="owner")
    assert owner.user == third_user  # the admin succeeds
    assert Community.objects.get(pk=community["id"]).member_count == 2
    assert Community.objects.get(pk=lonely["id"]).status == "archived"


def test_community_reports_go_to_parent_scope(user):
    from university.community.content import CommunityAdapter

    MEMBERS[str(user.pk)] = [("institution", "inst-1")]
    from university.community import services

    community = services.create_community(
        creator=user, data={"name": "Linked"}, scope_type="institution", scope_id="inst-1"
    )
    ref = CommunityAdapter().resolve(community.pk)
    assert ref.scope == ("institution", "inst-1") and ref.author_id == str(user.pk)
    CommunityAdapter().hide(community.pk, reason="abuse")
    community.refresh_from_db()
    assert community.status == "suspended"


@pytest.mark.security
def test_posting_and_commenting_policies(auth_client, user, other_user, third_user):
    from university.core.audiences import can_post_to

    community = create(auth_client(user), "Announcements", posting_policy="moderators", commenting_policy="members")
    assert community["posting_policy"] == "moderators" and community["commenting_policy"] == "members"
    join(auth_client(other_user), community)
    join(auth_client(third_user), community)
    auth_client(user).patch(f"{BASE}/{community['id']}/members/{other_user.pk}/", {"role": "moderator"}, format="json")
    cid = community["id"]

    def fresh(u):
        return type(u).objects.get(pk=u.pk)

    assert can_post_to(fresh(user), "community", cid, "social.post")  # owner
    assert can_post_to(fresh(other_user), "community", cid, "social.post")  # moderator
    assert not can_post_to(fresh(third_user), "community", cid, "social.post")  # member
    assert can_post_to(fresh(third_user), "community", cid, "social.comment")
    outsider = create_user("out@example.com", handle="outsider")
    assert not can_post_to(outsider, "community", cid, "social.comment")
    # Admins change the policy; members cannot.
    url = f"{BASE}/{cid}/"
    assert auth_client(third_user).patch(url, {"commenting_policy": "disabled"}, format="json").status_code == 403
    assert auth_client(user).patch(url, {"commenting_policy": "disabled"}, format="json").status_code == 200
    assert not can_post_to(fresh(user), "community", cid, "social.comment")
    assert auth_client(user).patch(url, {"posting_policy": "everyone"}, format="json").status_code == 400
    # Other audiences are not this module's business.
    assert can_post_to(fresh(third_user), "institution", "inst-1", "social.post")
