"""The visibility matrix — the core privacy guarantee of the social module."""

from __future__ import annotations

import itertools

import pytest
from django.contrib.auth.models import AnonymousUser

from tests.helpers import BASE, join_audience
from university.core.testing import create_user
from university.social import selectors
from university.social.models import Block, Follow, Post
from university.users.constants import UserStatus
from university.users.services import get_privacy_settings, update_settings

pytestmark = [pytest.mark.django_db, pytest.mark.security]


@pytest.fixture
def cast(db):
    author = create_user("author@example.com", handle="author")
    follower = create_user("follower@example.com", handle="follower")
    member = create_user("member@example.com", handle="member")
    stranger = create_user("stranger@example.com", handle="stranger")
    Follow.objects.create(follower=follower, followee=author)
    join_audience(author, "institution", "inst-1")
    join_audience(member, "institution", "inst-1")
    return {"author": author, "follower": follower, "member": member, "stranger": stranger, "anon": AnonymousUser()}


def _post(author, visibility, **extra):
    scope = {"scope_type": visibility, "scope_id": "inst-1"} if visibility == "institution" else {}
    return Post.objects.create(author=author, body=visibility, visibility=visibility, **scope, **extra)


EXPECTED = {
    #                author  follower member stranger anon
    "public": (True, True, True, True, True),
    "followers": (True, True, False, False, False),
    "private": (True, False, False, False, False),
    "institution": (True, False, True, False, False),
}
VIEWERS = ("author", "follower", "member", "stranger", "anon")


@pytest.mark.parametrize("visibility", list(EXPECTED))
def test_visibility_matrix(cast, visibility):
    post = _post(cast["author"], visibility)
    for viewer_name, expected in zip(VIEWERS, EXPECTED[visibility], strict=True):
        viewer = cast[viewer_name]
        in_query = selectors.visible_posts(viewer).filter(pk=post.pk).exists()
        in_python = selectors.can_view_post(viewer, Post.objects.get(pk=post.pk))
        assert in_query == in_python == expected, (visibility, viewer_name)


@pytest.mark.parametrize(
    ("profile_visibility", "anon", "stranger", "follower"),
    [
        ("public", True, True, True),
        ("members", False, True, True),
        ("private", False, False, True),
    ],
)
def test_profile_privacy_limits_public_posts(cast, profile_visibility, anon, stranger, follower):
    update_settings(get_privacy_settings(cast["author"]), {"profile_visibility": profile_visibility})
    post = _post(cast["author"], "public")
    for name, expected in (("anon", anon), ("stranger", stranger), ("follower", follower)):
        viewer = cast[name]
        fresh = Post.objects.select_related("author__privacy_settings").get(pk=post.pk)
        assert selectors.visible_posts(viewer).filter(pk=post.pk).exists() == expected, name
        assert selectors.can_view_post(viewer, fresh) == expected, name


def test_blocks_hide_content_both_ways(cast):
    post = _post(cast["author"], "public")
    Block.objects.create(blocker=cast["author"], blocked=cast["stranger"])
    assert not selectors.visible_posts(cast["stranger"]).filter(pk=post.pk).exists()
    assert not selectors.can_view_post(cast["stranger"], post)
    theirs = _post(cast["stranger"], "public")
    assert not selectors.visible_posts(cast["author"]).filter(pk=theirs.pk).exists()


def test_pending_follow_is_not_a_follower(cast):
    pending = create_user("pending@example.com", handle="pending")
    Follow.objects.create(follower=pending, followee=cast["author"], status="pending")
    post = _post(cast["author"], "followers")
    assert not selectors.can_view_post(pending, post)


def test_hidden_deleted_and_inactive_authors(cast):
    hidden = _post(cast["author"], "public", status="hidden")
    assert not selectors.can_view_post(cast["stranger"], hidden)
    assert selectors.can_view_post(cast["author"], hidden)
    deleted = _post(cast["author"], "public")
    deleted.delete()
    assert not selectors.visible_posts(cast["author"]).filter(pk=deleted.pk).exists()
    live = _post(cast["author"], "public")
    type(cast["author"]).objects.filter(pk=cast["author"].pk).update(status=UserStatus.SUSPENDED)
    assert not selectors.visible_posts(cast["stranger"]).filter(pk=live.pk).exists()


def test_query_and_python_agree_on_random_combinations(cast):
    """Exhaustive cross-check of SQL and Python rules across states."""
    combos = itertools.product(EXPECTED, ("published", "hidden", "pending_review"))
    for visibility, status in combos:
        post = _post(cast["author"], visibility, status=status)
        for name in VIEWERS:
            viewer = cast[name]
            fresh = Post.objects.select_related("author__privacy_settings").get(pk=post.pk)
            assert selectors.visible_posts(viewer).filter(pk=post.pk).exists() == selectors.can_view_post(
                viewer, fresh
            ), (visibility, status, name)


def test_api_returns_404_for_invisible_posts(cast, auth_client, api_client):
    private = _post(cast["author"], "private")
    followers = _post(cast["author"], "followers")
    assert api_client.get(f"{BASE}/posts/{private.pk}/").status_code == 404
    assert auth_client(cast["stranger"]).get(f"{BASE}/posts/{followers.pk}/").status_code == 404
    assert auth_client(cast["follower"]).get(f"{BASE}/posts/{followers.pk}/").status_code == 200
    # Interactions on invisible posts also 404 — no oracle.
    stranger = auth_client(cast["stranger"])
    for method, url, payload in (
        ("post", f"{BASE}/posts/{followers.pk}/reaction/", {"kind": "like"}),
        ("post", f"{BASE}/posts/{followers.pk}/comments/", {"body": "hi"}),
        ("post", f"{BASE}/posts/{followers.pk}/bookmark/", {}),
        ("get", f"{BASE}/posts/{followers.pk}/comments/", None),
    ):
        response = getattr(stranger, method)(url, payload, format="json") if payload is not None else stranger.get(url)
        assert response.status_code == 404, url
