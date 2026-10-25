"""Posts: creation, parsing, editing, deletion, reposts, spam, rate limits."""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import override_settings
from django.utils import timezone

from tests.helpers import BASE, join_audience, make_post
from university.audit.models import AuditLog
from university.core.events import event_bus
from university.permissions.services import assign_role
from university.social.models import Hashtag, Post, PostMention, PostRevision, SocialProfile

pytestmark = pytest.mark.django_db


def test_create_post_with_parsing(auth_client, user, other_user):
    client = auth_client(user)
    post = make_post(
        client, "Exams at #UNILAG today with @grace and @nobody — see https://exams.example.edu/t #exams #Exams"
    )
    assert post["author"]["handle"] == "ada"
    assert sorted(post["hashtags"]) == ["exams", "unilag"]  # case-insensitive, de-duplicated
    assert [m["handle"] for m in post["mentions"]] == ["grace"]
    assert post["links"] == ["https://exams.example.edu/t"]
    assert post["visibility"] == "public" and post["status"] == "published"
    assert post["viewer"] == {"reaction": None, "bookmarked": False, "reposted": False, "is_author": True}
    assert Hashtag.objects.get(name="exams").posts_count == 1
    assert SocialProfile.objects.get(user=user).posts_count == 1


def test_unicode_hashtags(auth_client, user):
    post = make_post(auth_client(user), "Ẹ ku àárọ̀ #Ọ̀rọ̀ #naija2026")
    assert "naija2026" in post["hashtags"] and len(post["hashtags"]) == 2


def test_validation(auth_client, user):
    client = auth_client(user)
    assert client.post(f"{BASE}/posts/", {"body": "   "}, format="json").json()["error"]["code"] == "empty_post"
    with override_settings(UNIVERSITY={"SOCIAL": {"POST_MAX_LENGTH": 10}}):
        assert client.post(f"{BASE}/posts/", {"body": "x" * 11}, format="json").status_code == 400
    assert client.post(f"{BASE}/posts/", {"body": "x", "location": "Lagos"}, format="json").status_code == 400
    assert client.post(f"{BASE}/posts/", {"body": "x", "visibility": "galaxy"}, format="json").status_code == 400
    assert client.post(f"{BASE}/posts/", {"body": "x", "audience_id": "abc"}, format="json").status_code == 400


@pytest.mark.security
def test_mass_assignment_ignored(auth_client, user, other_user):
    post = make_post(
        auth_client(user),
        "Mine",
        author=str(other_user.pk),
        status="hidden",
        reaction_count=999,
        is_author=False,
    )
    stored = Post.objects.get(pk=post["id"])
    assert stored.author == user and stored.status == "published" and stored.reaction_count == 0


def test_audience_posts_require_membership(auth_client, user):
    client = auth_client(user)
    response = client.post(
        f"{BASE}/posts/", {"body": "Hi", "visibility": "institution", "audience_id": "inst-1"}, format="json"
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "not_audience_member"
    assert client.post(f"{BASE}/posts/", {"body": "Hi", "visibility": "institution"}, format="json").status_code == 400
    join_audience(user, "institution", "inst-1")
    post = make_post(auth_client(user), "Hi members", visibility="institution", audience_id="inst-1")
    assert post["audience"] == {"type": "institution", "id": "inst-1"}


def test_default_visibility_from_profile(auth_client, user):
    client = auth_client(user)
    client.patch(f"{BASE}/me/profile/", {"default_post_visibility": "followers"}, format="json")
    assert make_post(client, "x")["visibility"] == "followers"
    bad = client.patch(f"{BASE}/me/profile/", {"default_post_visibility": "institution"}, format="json")
    assert bad.status_code == 400


def test_edit_keeps_revisions_and_reparses(auth_client, user, other_user):
    client = auth_client(user)
    post = make_post(client, "Original #one")
    edited = client.patch(f"{BASE}/posts/{post['id']}/", {"body": "Edited #two @grace"}, format="json")
    assert edited.status_code == 200
    data = edited.json()
    assert data["body"] == "Edited #two @grace" and data["edited_at"] and data["hashtags"] == ["two"]
    assert PostRevision.objects.get(post_id=post["id"]).body == "Original #one"
    assert Hashtag.objects.get(name="one").posts_count == 0
    assert PostMention.objects.filter(post_id=post["id"], user=other_user).exists()


def test_edit_window_and_ownership(auth_client, user, other_user):
    post = make_post(auth_client(user), "x")
    assert (
        auth_client(other_user).patch(f"{BASE}/posts/{post['id']}/", {"body": "hack"}, format="json").status_code == 403
    )
    Post.objects.filter(pk=post["id"]).update(created_at=timezone.now() - dt.timedelta(days=2))
    late = auth_client(user).patch(f"{BASE}/posts/{post['id']}/", {"body": "late"}, format="json")
    assert late.json()["error"]["code"] == "edit_window_closed"
    assert (
        auth_client(user).patch(f"{BASE}/posts/{post['id']}/", {"comments_enabled": False}, format="json").status_code
        == 200
    )


def test_delete_post(auth_client, api_client, user, other_user, superuser):
    post = make_post(auth_client(user), "bye #tag")
    assert auth_client(other_user).delete(f"{BASE}/posts/{post['id']}/").status_code == 403
    assert auth_client(user).delete(f"{BASE}/posts/{post['id']}/").status_code == 204
    assert api_client.get(f"{BASE}/posts/{post['id']}/").status_code == 404
    assert Post.all_objects.filter(pk=post["id"]).exists()  # soft delete
    assert SocialProfile.objects.get(user=user).posts_count == 0
    assert Hashtag.objects.get(name="tag").posts_count == 0
    # Moderator removal is audited.
    other = make_post(auth_client(other_user), "rule breaking")
    assert auth_client(superuser).delete(f"{BASE}/posts/{other['id']}/").status_code == 204
    assert AuditLog.objects.filter(action="social.post.removed", actor=superuser).exists()


@pytest.mark.security
def test_private_post_delete_is_404_for_strangers(auth_client, user, other_user):
    post = make_post(auth_client(user), "secret", visibility="private")
    assert auth_client(other_user).delete(f"{BASE}/posts/{post['id']}/").status_code == 404


def test_repost_and_quote(auth_client, user, other_user):
    original = make_post(auth_client(user), "Original")
    client = auth_client(other_user)
    repost = client.post(f"{BASE}/posts/{original['id']}/repost/", {}, format="json")
    assert repost.status_code == 201
    assert repost.json()["is_repost"] and repost.json()["repost_of"]["body"] == "Original"
    assert client.post(f"{BASE}/posts/{original['id']}/repost/", {}, format="json").status_code == 409
    quote = client.post(f"{BASE}/posts/{original['id']}/repost/", {"body": "So true"}, format="json")
    assert quote.status_code == 201 and not quote.json()["is_repost"]
    assert Post.objects.get(pk=original["id"]).repost_count == 2
    viewer = client.get(f"{BASE}/posts/{original['id']}/").json()["viewer"]
    assert viewer["reposted"] is True
    # Reposting a repost targets the original.
    third = auth_client(user).post(f"{BASE}/posts/{repost.json()['id']}/repost/", {}, format="json")
    assert third.status_code == 201 and third.json()["repost_of"]["id"] == original["id"]
    assert client.delete(f"{BASE}/posts/{original['id']}/repost/").status_code == 204
    assert Post.objects.get(pk=original["id"]).repost_count == 2


@pytest.mark.security
def test_only_public_posts_can_be_reposted(auth_client, user, other_user):
    client = auth_client(user)
    followers_only = make_post(client, "followers", visibility="followers")
    other_client = auth_client(other_user)
    other_client.post(f"{BASE}/users/{user.pk}/follow/")
    response = other_client.post(f"{BASE}/posts/{followers_only['id']}/repost/", {}, format="json")
    assert response.status_code == 400 and response.json()["error"]["code"] == "not_repostable"


def test_repost_of_deleted_original_shows_unavailable(auth_client, user, other_user):
    original = make_post(auth_client(user), "Original")
    repost = (
        auth_client(other_user).post(f"{BASE}/posts/{original['id']}/repost/", {"body": "quote"}, format="json").json()
    )
    auth_client(user).delete(f"{BASE}/posts/{original['id']}/")
    data = auth_client(other_user).get(f"{BASE}/posts/{repost['id']}/").json()
    assert data["repost_of"] == {"id": original["id"], "unavailable": True}


def test_spam_screening(auth_client, api_client, user, superuser):
    client = auth_client(user)
    with override_settings(UNIVERSITY={"PROVIDERS": {"SPAM_OPTIONS": {"blocked_terms": ["buy followers"]}}}):
        from university.core import providers

        providers.reset_provider_cache()
        rejected = client.post(f"{BASE}/posts/", {"body": "Cheap! buy followers now"}, format="json")
        assert rejected.status_code == 400 and rejected.json()["error"]["code"] == "content_rejected"
        providers.reset_provider_cache()
    held = make_post(client, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA LOOK AT THIS NOW EVERYONE PLEASE")
    assert held["status"] == "pending_review"
    assert api_client.get(f"{BASE}/posts/{held['id']}/").status_code == 404  # only the author sees it
    assert auth_client(superuser).post(f"{BASE}/posts/{held['id']}/restore/", {}, format="json").status_code == 204
    assert api_client.get(f"{BASE}/posts/{held['id']}/").status_code == 200


def test_post_rate_limit(auth_client, user):
    client = auth_client(user)
    with override_settings(UNIVERSITY={"THROTTLE_RATES": {"social_post": "2/hour"}}):
        make_post(client, "1")
        make_post(client, "2")
        response = client.post(f"{BASE}/posts/", {"body": "3"}, format="json")
        assert response.status_code == 429


def test_events_published_with_ids_only(auth_client, user, other_user):
    seen = []
    event_bus.subscribe("social.*", seen.append)
    try:
        make_post(auth_client(user), "Hi @grace")
    finally:
        event_bus.unsubscribe("social.*", seen.append)
    names = {e.name for e in seen}
    assert {"social.post.created", "social.mention.created"} <= names
    mention = next(e for e in seen if e.name == "social.mention.created")
    assert mention.payload["mentioned_user_id"] == str(other_user.pk)
    assert all("body" not in e.payload for e in seen)


def test_moderation_scoped_to_audience(auth_client, user, other_user, third_user):
    from university.permissions.models import Role
    from university.permissions.scopes import Scope

    join_audience(user, "institution", "inst-1")
    scoped = make_post(auth_client(user), "inside", visibility="institution", audience_id="inst-1")
    public = make_post(auth_client(user), "outside")
    Role.objects.create(key="inst_mod", name="x", scope_type="institution", permissions=["social.content.moderate"])
    assign_role(user=third_user, role_key="inst_mod", scope=Scope("institution", "inst-1"))
    mod = auth_client(third_user)
    assert mod.post(f"{BASE}/posts/{public['id']}/hide/", {"reason": "x"}, format="json").status_code == 403
    assert mod.post(f"{BASE}/posts/{scoped['id']}/hide/", {"reason": "spam"}, format="json").status_code == 204
    assert auth_client(other_user).post(f"{BASE}/posts/{scoped['id']}/hide/", {}, format="json").status_code == 403
    assert Post.objects.get(pk=scoped["id"]).status == "hidden"
    assert AuditLog.objects.filter(action="social.post.hidden", actor=third_user).exists()
    # The author still sees it, with the reason.
    own = auth_client(user).get(f"{BASE}/posts/{scoped['id']}/").json()
    assert own["status"] == "hidden" and own["moderation_reason"] == "spam"
