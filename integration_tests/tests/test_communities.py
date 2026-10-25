"""Communities composed with social, anonymous, moderation and institution."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from university.community import services as community_services
from university.core.testing import create_user
from university.moderation.models import ModerationCase

pytestmark = pytest.mark.django_db


def aged(user):
    type(user).objects.filter(pk=user.pk).update(created_at=timezone.now() - dt.timedelta(days=30))
    user.refresh_from_db()
    return user


@pytest.fixture
def club(user):
    return community_services.create_community(creator=user, data={"name": "Robotics", "privacy": "restricted"})


def test_community_only_social_posts(auth_client, user, other_user, club):
    post = auth_client(user).post(
        "/api/v1/social/posts/",
        {"body": "Members only", "visibility": "community", "audience_id": str(club.pk)},
        format="json",
    )
    assert post.status_code == 201
    url = f"/api/v1/social/posts/{post.json()['id']}/"
    assert auth_client(other_user).get(url).status_code == 404
    auth_client(other_user).post(f"/api/v1/communities/{club.pk}/join/")  # pending (restricted)
    assert auth_client(other_user).get(url).status_code == 404
    auth_client(user).post(f"/api/v1/communities/{club.pk}/members/{other_user.pk}/approve/")
    assert auth_client(other_user).get(url).status_code == 200
    feed = auth_client(other_user).get(f"/api/v1/social/audiences/community/{club.pk}/posts/").json()["results"]
    assert [p["body"] for p in feed] == ["Members only"]


def test_anonymous_community_board(auth_client, user, other_user, club):
    aged(user)
    created = auth_client(user).post(
        "/api/v1/anonymous/posts/",
        {"body": "Anon in club", "visibility": "community", "audience_id": str(club.pk)},
        format="json",
    )
    assert created.status_code == 201
    assert auth_client(other_user).get("/api/v1/anonymous/posts/").json()["results"] == []


def test_community_moderators_moderate_their_own_community(auth_client, user, other_user, third_party, club):
    for u in (other_user, third_party):
        auth_client(u).post(f"/api/v1/communities/{club.pk}/join/")
        auth_client(user).post(f"/api/v1/communities/{club.pk}/members/{u.pk}/approve/")
    auth_client(user).patch(
        f"/api/v1/communities/{club.pk}/members/{other_user.pk}/", {"role": "moderator"}, format="json"
    )
    post = (
        auth_client(third_party)
        .post(
            "/api/v1/social/posts/",
            {"body": "rude", "visibility": "community", "audience_id": str(club.pk)},
            format="json",
        )
        .json()
    )
    outside = auth_client(third_party).post("/api/v1/social/posts/", {"body": "public rude"}, format="json").json()
    for target in (post, outside):
        auth_client(user).post(
            "/api/v1/moderation/reports/",
            {"content_type": "social.post", "object_id": target["id"], "reason": "harassment"},
            format="json",
        )
    queue = auth_client(other_user).get("/api/v1/moderation/cases/").json()["results"]
    assert [c["object_id"] for c in queue] == [post["id"]]  # only their community's cases
    case = ModerationCase.objects.get(object_id=post["id"])
    other_case = ModerationCase.objects.get(object_id=outside["id"])
    act = {"action": "hide", "reason": "community rules"}
    assert (
        auth_client(other_user).post(f"/api/v1/moderation/cases/{case.pk}/actions/", act, format="json").status_code
        == 201
    )
    assert (
        auth_client(other_user)
        .post(f"/api/v1/moderation/cases/{other_case.pk}/actions/", act, format="json")
        .status_code
        == 403
    )
    # Social's own moderation endpoint honours the same implicit authority.
    assert (
        auth_client(other_user).post(f"/api/v1/social/posts/{post['id']}/restore/", {}, format="json").status_code
        == 204
    )


@pytest.fixture
def third_party(db):
    return create_user("ngozi@example.com", handle="ngozi")


def test_posting_policies_apply_to_social_and_anonymous(auth_client, user, other_user, third_party):
    announcements = community_services.create_community(
        creator=user, data={"name": "Announcements", "posting_policy": "moderators", "commenting_policy": "members"}
    )
    for u in (other_user, third_party):
        auth_client(u).post(f"/api/v1/communities/{announcements.pk}/join/")
    auth_client(user).patch(
        f"/api/v1/communities/{announcements.pk}/members/{other_user.pk}/", {"role": "moderator"}, format="json"
    )
    payload = {"body": "Exam timetable is out", "visibility": "community", "audience_id": str(announcements.pk)}
    member_post = auth_client(third_party).post("/api/v1/social/posts/", payload, format="json")
    assert member_post.status_code == 403 and member_post.json()["error"]["code"] == "audience_posting_restricted"
    mod_post = auth_client(other_user).post("/api/v1/social/posts/", payload, format="json")
    assert mod_post.status_code == 201
    # Members may still comment under the "members" commenting policy...
    comments_url = f"/api/v1/social/posts/{mod_post.json()['id']}/comments/"
    assert auth_client(third_party).post(comments_url, {"body": "Thanks!"}, format="json").status_code == 201
    # ...until comments are disabled.
    auth_client(user).patch(
        f"/api/v1/communities/{announcements.pk}/", {"commenting_policy": "disabled"}, format="json"
    )
    blocked = auth_client(third_party).post(comments_url, {"body": "More?"}, format="json")
    assert blocked.json()["error"]["code"] == "audience_posting_restricted"
    # Anonymous posting follows the same policy.
    aged(third_party)
    anon = auth_client(third_party).post("/api/v1/anonymous/posts/", payload, format="json")
    assert anon.json()["error"]["code"] == "audience_posting_restricted"
