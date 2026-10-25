"""Follow / block / mute / restrict, and their effect across the platform."""

from __future__ import annotations

import pytest

from tests.helpers import BASE, make_post
from university.core.events import event_bus
from university.social.models import Block, Follow, PostMention, SocialProfile

pytestmark = pytest.mark.django_db


def _counts(user):
    p = SocialProfile.objects.get(user=user)
    return p.followers_count, p.following_count


def test_follow_unfollow_counts_and_idempotency(auth_client, user, other_user):
    client = auth_client(user)
    assert client.post(f"{BASE}/users/{other_user.pk}/follow/").json() == {"status": "active"}
    assert client.post(f"{BASE}/users/{other_user.pk}/follow/").json() == {"status": "active"}
    assert _counts(other_user) == (1, 0) and _counts(user) == (0, 1)
    followers = auth_client(other_user).get(f"{BASE}/users/{other_user.pk}/followers/").json()
    assert [u["handle"] for u in followers["results"]] == ["ada"]
    assert client.delete(f"{BASE}/users/{other_user.pk}/follow/").status_code == 204
    assert client.delete(f"{BASE}/users/{other_user.pk}/follow/").status_code == 204
    assert _counts(other_user) == (0, 0)


def test_cannot_follow_self_or_unknown(auth_client, user):
    client = auth_client(user)
    assert client.post(f"{BASE}/users/{user.pk}/follow/").status_code == 400
    assert client.post(f"{BASE}/users/00000000-0000-0000-0000-000000000009/follow/").status_code == 404


def test_follow_approval_flow(auth_client, user, other_user):
    auth_client(other_user).patch(f"{BASE}/me/profile/", {"requires_follow_approval": True}, format="json")
    assert auth_client(user).post(f"{BASE}/users/{other_user.pk}/follow/").json() == {"status": "pending"}
    assert _counts(other_user) == (0, 0)
    # Protected accounts hide their follower lists from non-followers.
    assert auth_client(user).get(f"{BASE}/users/{other_user.pk}/followers/").status_code == 404
    requests = auth_client(other_user).get(f"{BASE}/me/follow-requests/").json()["results"]
    assert requests[0]["user"]["handle"] == "ada"
    # Only the followee can approve.
    assert auth_client(user).post(f"{BASE}/me/follow-requests/{requests[0]['id']}/approve/").status_code == 404
    assert auth_client(other_user).post(f"{BASE}/me/follow-requests/{requests[0]['id']}/approve/").status_code == 204
    assert _counts(other_user) == (1, 0)
    assert auth_client(user).get(f"{BASE}/users/{other_user.pk}/followers/").status_code == 200


def test_remove_follower(auth_client, user, other_user):
    auth_client(user).post(f"{BASE}/users/{other_user.pk}/follow/")
    assert auth_client(other_user).delete(f"{BASE}/me/followers/{user.pk}/").status_code == 204
    assert not Follow.objects.exists() and _counts(other_user) == (0, 0)


@pytest.mark.security
def test_block_is_enforced_everywhere(auth_client, api_client, user, other_user):
    ada, grace = auth_client(user), auth_client(other_user)
    ada.post(f"{BASE}/users/{other_user.pk}/follow/")
    grace.post(f"{BASE}/users/{user.pk}/follow/")
    post = make_post(ada, "hello")
    assert grace.post(f"{BASE}/users/{user.pk}/block/").status_code == 204
    assert grace.post(f"{BASE}/users/{user.pk}/block/").status_code == 204  # idempotent
    # Follows severed both ways, counters corrected.
    assert not Follow.objects.exists() and _counts(user) == (0, 0) and _counts(other_user) == (0, 0)
    # Profiles (Core endpoint, via hook) are hidden both ways.
    assert ada.get(f"/api/v1/users/{other_user.pk}/").status_code == 404
    assert grace.get(f"/api/v1/users/{user.pk}/").status_code == 404
    assert api_client.get(f"/api/v1/users/{user.pk}/").status_code == 200
    # Content and interactions blocked.
    assert grace.get(f"{BASE}/posts/{post['id']}/").status_code == 404
    assert ada.post(f"{BASE}/users/{other_user.pk}/follow/").status_code == 404
    assert grace.get(f"{BASE}/users/{user.pk}/posts/").status_code == 404
    # Mentions of a blocking user are dropped silently.
    mention = make_post(ada, "hey @grace")
    assert not PostMention.objects.filter(post_id=mention["id"]).exists()
    assert [u["handle"] for u in grace.get(f"{BASE}/me/blocks/").json()["results"]] == ["ada"]
    assert grace.delete(f"{BASE}/users/{user.pk}/block/").status_code == 204
    assert not Block.objects.exists()


def test_block_event_and_unknown_target(auth_client, user, other_user):
    seen = []
    event_bus.subscribe("social.block.created", seen.append)
    try:
        auth_client(user).post(f"{BASE}/users/{other_user.pk}/block/")
    finally:
        event_bus.unsubscribe("social.block.created", seen.append)
    assert len(seen) == 1
    assert auth_client(user).post(f"{BASE}/users/00000000-0000-0000-0000-000000000009/block/").status_code == 404


def test_mute_hides_from_feeds_not_timelines(auth_client, user, other_user):
    ada, grace = auth_client(user), auth_client(other_user)
    ada.post(f"{BASE}/users/{other_user.pk}/follow/")
    make_post(grace, "noisy")
    assert len(ada.get(f"{BASE}/feeds/home/").json()["results"]) == 1
    ada.post(f"{BASE}/users/{other_user.pk}/mute/")
    assert ada.get(f"{BASE}/feeds/home/").json()["results"] == []
    assert ada.get(f"{BASE}/feeds/explore/").json()["results"] == []
    assert len(ada.get(f"{BASE}/users/{other_user.pk}/posts/").json()["results"]) == 1
    assert [u["handle"] for u in ada.get(f"{BASE}/me/mutes/").json()["results"]] == ["grace"]
    ada.delete(f"{BASE}/users/{other_user.pk}/mute/")
    assert len(ada.get(f"{BASE}/feeds/home/").json()["results"]) == 1


def test_mention_policies(auth_client, user, other_user):
    grace = auth_client(other_user)
    grace.patch(f"{BASE}/me/profile/", {"allow_mentions_from": "nobody"}, format="json")
    post = make_post(auth_client(user), "hi @grace")
    assert post["mentions"] == []
    grace.patch(f"{BASE}/me/profile/", {"allow_mentions_from": "following"}, format="json")
    assert make_post(auth_client(user), "hi again @grace")["mentions"] == []
    grace.post(f"{BASE}/users/{user.pk}/follow/")
    assert [m["handle"] for m in make_post(auth_client(user), "now @grace")["mentions"]] == ["grace"]


def test_public_profile_social_extras(auth_client, api_client, user, other_user):
    auth_client(other_user).post(f"{BASE}/users/{user.pk}/follow/")
    auth_client(user).patch(f"{BASE}/me/profile/", {"bio": "CS @ UNILAG"}, format="json")
    social = auth_client(other_user).get(f"/api/v1/users/{user.pk}/").json()["extras"]["social"]
    assert social["bio"] == "CS @ UNILAG" and social["followers_count"] == 1
    assert social["relationship"] == {"following": "active", "followed_by": False}
    assert "relationship" not in api_client.get(f"/api/v1/users/{user.pk}/").json()["extras"]["social"]


def test_profile_counters_are_read_only(auth_client, user):
    response = auth_client(user).patch(f"{BASE}/me/profile/", {"followers_count": 10_000}, format="json")
    assert response.status_code == 200 and response.json()["followers_count"] == 0
