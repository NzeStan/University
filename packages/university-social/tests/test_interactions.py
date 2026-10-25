"""Comments, reactions, bookmarks, polls and media."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from tests.helpers import BASE, PNG, make_post
from university.audit.models import AuditLog
from university.social.models import Comment, Poll, Post, PostMedia

pytestmark = pytest.mark.django_db


# ----------------------------------------------------------------- comments
def test_comments_and_flattened_replies(auth_client, api_client, user, other_user, third_user):
    post = make_post(auth_client(user), "Discuss")
    grace, ngozi = auth_client(other_user), auth_client(third_user)
    top = grace.post(f"{BASE}/posts/{post['id']}/comments/", {"body": "First @ada"}, format="json").json()
    reply = ngozi.post(
        f"{BASE}/posts/{post['id']}/comments/", {"body": "Reply", "parent": top["id"]}, format="json"
    ).json()
    nested = grace.post(
        f"{BASE}/posts/{post['id']}/comments/", {"body": "Deep", "parent": reply["id"]}, format="json"
    ).json()
    assert reply["parent"] == top["id"] and nested["parent"] == top["id"]  # two levels max
    top_level = api_client.get(f"{BASE}/posts/{post['id']}/comments/").json()["results"]
    assert [c["body"] for c in top_level] == ["First @ada"] and top_level[0]["reply_count"] == 2
    replies = api_client.get(f"{BASE}/posts/{post['id']}/comments/?parent={top['id']}").json()["results"]
    assert [c["body"] for c in replies] == ["Reply", "Deep"]
    assert Post.objects.get(pk=post["id"]).comment_count == 3


def test_comment_permissions(auth_client, user, other_user, third_user, superuser):
    ada, grace = auth_client(user), auth_client(other_user)
    post = make_post(ada, "mine")
    comment = grace.post(f"{BASE}/posts/{post['id']}/comments/", {"body": "c"}, format="json").json()
    assert (
        auth_client(third_user).patch(f"{BASE}/comments/{comment['id']}/", {"body": "x"}, format="json").status_code
        == 403
    )
    assert auth_client(third_user).delete(f"{BASE}/comments/{comment['id']}/").status_code == 403
    assert grace.patch(f"{BASE}/comments/{comment['id']}/", {"body": "edited"}, format="json").json()["edited_at"]
    # The post's author may remove comments on their post.
    assert ada.delete(f"{BASE}/comments/{comment['id']}/").status_code == 204
    assert Post.objects.get(pk=post["id"]).comment_count == 0
    other = grace.post(f"{BASE}/posts/{post['id']}/comments/", {"body": "c2"}, format="json").json()
    assert auth_client(superuser).delete(f"{BASE}/comments/{other['id']}/").status_code == 204
    assert AuditLog.objects.filter(action="social.comment.removed").exists()


def test_comments_disabled(auth_client, user, other_user):
    post = make_post(auth_client(user), "quiet", comments_enabled=False)
    response = auth_client(other_user).post(f"{BASE}/posts/{post['id']}/comments/", {"body": "hi"}, format="json")
    assert response.status_code == 403 and response.json()["error"]["code"] == "comments_disabled"


@pytest.mark.security
def test_restricted_comments_visible_only_to_the_pair(auth_client, api_client, user, other_user, third_user):
    ada, grace = auth_client(user), auth_client(other_user)
    post = make_post(ada, "post")
    ada.post(f"{BASE}/users/{other_user.pk}/restrict/")
    grace.post(f"{BASE}/posts/{post['id']}/comments/", {"body": "troll"}, format="json")
    url = f"{BASE}/posts/{post['id']}/comments/"
    assert [c["body"] for c in grace.get(url).json()["results"]] == ["troll"]  # unaware
    assert [c["body"] for c in ada.get(url).json()["results"]] == ["troll"]
    assert auth_client(third_user).get(url).json()["results"] == []
    assert api_client.get(url).json()["results"] == []


@pytest.mark.security
def test_blocked_users_comments_are_hidden(auth_client, user, other_user, third_user):
    post = make_post(auth_client(third_user), "public")
    auth_client(other_user).post(f"{BASE}/posts/{post['id']}/comments/", {"body": "from grace"}, format="json")
    auth_client(user).post(f"{BASE}/users/{other_user.pk}/block/")
    assert auth_client(user).get(f"{BASE}/posts/{post['id']}/comments/").json()["results"] == []


# ---------------------------------------------------------------- reactions
def test_reactions_are_idempotent_and_switchable(auth_client, user, other_user):
    post = make_post(auth_client(user), "react")
    grace = auth_client(other_user)
    assert (
        grace.post(f"{BASE}/posts/{post['id']}/reaction/", {"kind": "like"}, format="json").json()["counts"][
            "reactions"
        ]
        == 1
    )
    again = grace.post(f"{BASE}/posts/{post['id']}/reaction/", {"kind": "love"}, format="json").json()
    assert again["counts"]["reactions"] == 1 and again["viewer"]["reaction"] == "love"
    assert grace.post(f"{BASE}/posts/{post['id']}/reaction/", {"kind": "meh"}, format="json").status_code == 400
    assert grace.delete(f"{BASE}/posts/{post['id']}/reaction/").status_code == 204
    assert grace.delete(f"{BASE}/posts/{post['id']}/reaction/").status_code == 204
    assert Post.objects.get(pk=post["id"]).reaction_count == 0


def test_comment_reactions(auth_client, user, other_user):
    post = make_post(auth_client(user), "x")
    comment = auth_client(user).post(f"{BASE}/posts/{post['id']}/comments/", {"body": "c"}, format="json").json()
    grace = auth_client(other_user)
    assert grace.post(f"{BASE}/comments/{comment['id']}/reaction/", {"kind": "laugh"}, format="json").status_code == 204
    listed = grace.get(f"{BASE}/posts/{post['id']}/comments/").json()["results"][0]
    assert listed["reaction_count"] == 1 and listed["viewer_reaction"] == "laugh"
    grace.delete(f"{BASE}/comments/{comment['id']}/reaction/")
    assert Comment.objects.get(pk=comment["id"]).reaction_count == 0


def test_bookmarks(auth_client, user, other_user):
    post = make_post(auth_client(other_user), "save me")
    ada = auth_client(user)
    assert ada.post(f"{BASE}/posts/{post['id']}/bookmark/").status_code == 204
    assert ada.post(f"{BASE}/posts/{post['id']}/bookmark/").status_code == 204
    saved = ada.get(f"{BASE}/me/bookmarks/").json()["results"]
    assert [p["id"] for p in saved] == [post["id"]] and saved[0]["viewer"]["bookmarked"]
    # Bookmarked posts that become invisible drop out.
    auth_client(other_user).delete(f"{BASE}/posts/{post['id']}/")
    assert ada.get(f"{BASE}/me/bookmarks/").json()["results"] == []


# -------------------------------------------------------------------- polls
def test_single_choice_poll(auth_client, user, other_user):
    post = make_post(auth_client(user), "Best canteen?", poll={"options": ["Mama Put", "Buka"], "duration_hours": 24})
    options = post["poll"]["options"]
    grace = auth_client(other_user)
    voted = grace.post(f"{BASE}/posts/{post['id']}/poll/vote/", {"options": [options[0]["id"]]}, format="json").json()
    assert voted["poll"]["total_votes"] == 1 and voted["poll"]["options"][0]["voted"]
    assert (
        grace.post(f"{BASE}/posts/{post['id']}/poll/vote/", {"options": [options[1]["id"]]}, format="json").status_code
        == 409
    )
    both = auth_client(user).post(
        f"{BASE}/posts/{post['id']}/poll/vote/", {"options": [o["id"] for o in options]}, format="json"
    )
    assert both.status_code == 400


def test_multi_choice_and_closed_polls(auth_client, user, other_user):
    post = make_post(auth_client(user), "Pick", poll={"options": ["A", "B", "C"], "allows_multiple": True})
    ids = [o["id"] for o in post["poll"]["options"]]
    grace = auth_client(other_user)
    result = grace.post(f"{BASE}/posts/{post['id']}/poll/vote/", {"options": ids[:2]}, format="json").json()
    assert result["poll"]["total_votes"] == 1 and [o["vote_count"] for o in result["poll"]["options"]] == [1, 1, 0]
    Poll.objects.filter(post_id=post["id"]).update(closes_at=timezone.now() - dt.timedelta(minutes=1))
    closed = auth_client(user).post(f"{BASE}/posts/{post['id']}/poll/vote/", {"options": ids[:1]}, format="json")
    assert closed.json()["error"]["code"] == "poll_closed"


def test_poll_validation(auth_client, user):
    client = auth_client(user)
    assert client.post(f"{BASE}/posts/", {"poll": {"options": ["Only"]}}, format="json").status_code == 400
    assert client.post(f"{BASE}/posts/", {"poll": {"options": ["A", "a"]}}, format="json").status_code == 400
    assert (
        client.post(
            f"{BASE}/posts/", {"poll": {"options": ["A", "B"], "duration_hours": 10_000}}, format="json"
        ).status_code
        == 400
    )


# -------------------------------------------------------------------- media
def test_media_upload_and_attach(auth_client, api_client, user):
    client = auth_client(user)
    uploaded = client.post(
        f"{BASE}/media/", {"file": SimpleUploadedFile("pic.png", PNG), "alt_text": "Campus gate"}, format="multipart"
    )
    assert uploaded.status_code == 201
    media = uploaded.json()
    assert media["mime_type"] == "image/png" and media["url"].endswith(".png")
    post = make_post(client, "", media=[media["id"]])
    assert [m["alt_text"] for m in post["media"]] == ["Campus gate"]
    # Already attached media cannot be reused or deleted.
    assert client.post(f"{BASE}/posts/", {"body": "x", "media": [media["id"]]}, format="json").status_code == 400
    assert client.delete(f"{BASE}/media/{media['id']}/").status_code == 404


@pytest.mark.security
def test_media_validation_and_ownership(auth_client, user, other_user):
    client = auth_client(user)
    evil = client.post(
        f"{BASE}/media/", {"file": SimpleUploadedFile("x.png", b"<svg onload=alert(1)>")}, format="multipart"
    )
    assert evil.status_code == 400
    mismatch = client.post(f"{BASE}/media/", {"file": SimpleUploadedFile("photo.jpg", PNG)}, format="multipart")
    assert mismatch.status_code == 400  # extension must match the real content
    pdf = client.post(f"{BASE}/media/", {"file": SimpleUploadedFile("x.pdf", b"%PDF-1.4 hi")}, format="multipart")
    assert pdf.status_code == 400
    theirs = (
        auth_client(other_user)
        .post(f"{BASE}/media/", {"file": SimpleUploadedFile("a.png", PNG)}, format="multipart")
        .json()
    )
    # BOLA: attaching or deleting someone else's upload is refused.
    assert client.post(f"{BASE}/posts/", {"body": "x", "media": [theirs["id"]]}, format="json").status_code == 400
    assert client.delete(f"{BASE}/media/{theirs['id']}/").status_code == 404


def test_orphan_media_retention(auth_client, user):
    from university.core.retention import run_retention

    uploaded = (
        auth_client(user).post(f"{BASE}/media/", {"file": SimpleUploadedFile("a.png", PNG)}, format="multipart").json()
    )
    PostMedia.objects.filter(pk=uploaded["id"]).update(created_at=timezone.now() - dt.timedelta(days=2))
    assert run_retention(only=["social.orphan_media"]) == {"social.orphan_media": 1}
    assert not PostMedia.objects.exists()
