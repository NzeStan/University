"""Feeds, audiences, hashtags, performance, export and purge."""

from __future__ import annotations

import datetime as dt

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests.helpers import BASE, join_audience, make_post
from university.core.testing import create_user
from university.social.models import Follow, Post, SocialProfile

pytestmark = pytest.mark.django_db


def test_home_feed(auth_client, api_client, user, other_user, third_user):
    ada = auth_client(user)
    ada.post(f"{BASE}/users/{other_user.pk}/follow/")
    make_post(auth_client(other_user), "from followee")
    make_post(auth_client(third_user), "from stranger")
    make_post(ada, "mine")
    bodies = [p["body"] for p in ada.get(f"{BASE}/feeds/home/").json()["results"]]
    assert bodies == ["mine", "from followee"]
    assert api_client.get(f"{BASE}/feeds/home/").status_code == 401
    assert api_client.get(f"{BASE}/feeds/nope/").status_code == 404


def test_home_feed_includes_audiences(auth_client, user, other_user):
    join_audience(user, "campus", "c-1")
    join_audience(other_user, "campus", "c-1")
    make_post(auth_client(other_user), "campus news", visibility="campus", audience_id="c-1")
    assert [p["body"] for p in auth_client(user).get(f"{BASE}/feeds/home/").json()["results"]] == ["campus news"]


def test_explore_and_audience_feeds(auth_client, api_client, user, other_user, third_user):
    join_audience(user, "institution", "i-1")
    join_audience(other_user, "institution", "i-1")
    make_post(auth_client(user), "public one")
    make_post(auth_client(user), "members only", visibility="institution", audience_id="i-1")
    assert [p["body"] for p in api_client.get(f"{BASE}/feeds/explore/").json()["results"]] == ["public one"]
    url = f"{BASE}/audiences/institution/i-1/posts/"
    assert [p["body"] for p in auth_client(other_user).get(url).json()["results"]] == ["members only"]
    assert auth_client(third_user).get(url).json()["results"] == []
    assert api_client.get(f"{BASE}/audiences/planet/x/posts/").status_code == 404


def test_trending_ranks_by_velocity(auth_client, api_client, user, other_user):
    old_popular = make_post(auth_client(user), "old but popular")
    fresh_active = make_post(auth_client(user), "fresh and active")
    quiet = make_post(auth_client(user), "quiet")
    Post.objects.filter(pk=old_popular["id"]).update(
        reaction_count=50, created_at=timezone.now() - dt.timedelta(hours=60)
    )
    Post.objects.filter(pk=fresh_active["id"]).update(reaction_count=10, comment_count=5)
    data = api_client.get(f"{BASE}/feeds/trending/").json()
    # Velocity beats total likes: 50 likes 60h ago rank below a fresh, quiet post.
    assert [p["id"] for p in data["results"]] == [fresh_active["id"], quiet["id"], old_popular["id"]]
    assert len(api_client.get(f"{BASE}/feeds/trending/?limit=1").json()["results"]) == 1
    assert api_client.get(f"{BASE}/feeds/trending/?offset=abc").status_code == 400


def test_hashtag_feed_and_search(api_client, auth_client, user):
    make_post(auth_client(user), "#Hackathon this weekend")
    make_post(auth_client(user), "#hackathon prizes")
    assert len(api_client.get(f"{BASE}/hashtags/HACKATHON/posts/").json()["results"]) == 2
    assert api_client.get(f"{BASE}/hashtags/?q=hack").json() == [{"name": "hackathon", "posts_count": 2}]


def test_feed_query_count_is_constant(auth_client, user):
    """No N+1: feed cost doesn't grow with the number of posts."""
    authors = [create_user(f"a{i}@example.com", handle=f"author{i}") for i in range(6)]
    for author in authors:
        Follow.objects.create(follower=user, followee=author)
    client = auth_client(user)

    def run() -> int:
        with CaptureQueriesContext(connection) as ctx:
            assert client.get(f"{BASE}/feeds/home/").status_code == 200
        return len(ctx.captured_queries)

    for author in authors[:2]:
        make_post(auth_client(author), "post #tag @ada", poll={"options": ["a", "b"]})
    small = run()
    for author in authors[2:]:
        for _ in range(3):
            make_post(auth_client(author), "post #tag @ada", poll={"options": ["a", "b"]})
    assert run() <= small + 1


def test_data_export_includes_social(auth_client, user, other_user):
    ada = auth_client(user)
    make_post(ada, "exported")
    ada.post(f"{BASE}/users/{other_user.pk}/follow/")
    data = ada.get("/api/v1/me/export/").json()["social"]
    assert data["posts"][0]["body"] == "exported" and data["following"] == [str(other_user.pk)]


def test_purge_erases_content_and_fixes_counters(auth_client, user, other_user):
    from university.core.testing import PASSWORD
    from university.users.services import delete_account, purge_user

    grace_post = make_post(auth_client(other_user), "grace's")
    ada = auth_client(user)
    make_post(ada, "ada's")
    ada.post(f"{BASE}/posts/{grace_post['id']}/reaction/", {"kind": "like"}, format="json")
    ada.post(f"{BASE}/posts/{grace_post['id']}/comments/", {"body": "nice"}, format="json")
    ada.post(f"{BASE}/users/{other_user.pk}/follow/")
    delete_account(user, password=PASSWORD)
    purge_user(type(user).all_objects.get(pk=user.pk))
    assert not Post.all_objects.filter(author=user).exists()
    refreshed = Post.objects.get(pk=grace_post["id"])
    assert refreshed.reaction_count == 0 and refreshed.comment_count == 0
    assert SocialProfile.objects.get(user=other_user).followers_count == 0


def test_deleted_users_content_disappears(auth_client, api_client, user):
    from university.core.testing import PASSWORD
    from university.users.services import delete_account

    post = make_post(auth_client(user), "soon gone")
    delete_account(user, password=PASSWORD)
    assert api_client.get(f"{BASE}/posts/{post['id']}/").status_code == 404
    assert api_client.get(f"{BASE}/feeds/explore/").json()["results"] == []
