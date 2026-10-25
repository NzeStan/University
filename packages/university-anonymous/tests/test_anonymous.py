"""Anonymous posting: audiences, gates, comments, pseudonyms, reactions, moderation, reveal."""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import override_settings
from django.utils import timezone

from tests.conftest import veteran
from tests.helpers import BASE, post
from university.anonymous.models import AnonymousPost, RevealRequest
from university.audit.models import AuditLog
from university.core.testing import create_user

pytestmark = pytest.mark.django_db


# ------------------------------------------------------------------ posting
def test_post_visible_to_audience_only(auth_client, author, reader, outsider):
    created = post(auth_client(author))
    assert created["author"] == {"anonymous": True} and created["viewer"]["is_author"] is True
    assert created["status"] == "published"
    feed = auth_client(reader).get(f"{BASE}/posts/").json()["results"]
    assert [p["id"] for p in feed] == [created["id"]] and feed[0]["viewer"]["is_author"] is False
    assert "status" not in feed[0]
    assert auth_client(outsider).get(f"{BASE}/posts/").json()["results"] == []
    assert auth_client(outsider).get(f"{BASE}/posts/{created['id']}/").status_code == 404


def test_posting_rules(auth_client, author, outsider):
    client = auth_client(author)
    assert client.post(f"{BASE}/posts/", {"body": "x", "visibility": "public"}, format="json").status_code == 400
    assert client.post(f"{BASE}/posts/", {"body": "x", "visibility": "institution"}, format="json").status_code == 400
    wrong = client.post(
        f"{BASE}/posts/", {"body": "x", "visibility": "institution", "audience_id": "inst-9"}, format="json"
    )
    assert wrong.status_code == 403
    assert (
        auth_client(outsider)
        .post(f"{BASE}/posts/", {"body": "x", "visibility": "institution", "audience_id": "inst-1"}, format="json")
        .status_code
        == 403
    )


def test_public_anonymous_posts_are_opt_in(auth_client, author, outsider):
    with override_settings(UNIVERSITY={"ANONYMOUS": {"ALLOWED_VISIBILITIES": ["public", "institution"]}}):
        created = auth_client(author).post(f"{BASE}/posts/", {"body": "hi all", "visibility": "public"}, format="json")
        assert created.status_code == 201
        assert len(auth_client(outsider).get(f"{BASE}/posts/").json()["results"]) == 1


def test_abuse_gates(auth_client):
    newbie = create_user("new@example.com", handle="newbie")
    from tests.audience.apps import MEMBERS

    MEMBERS[str(newbie.pk)] = [("institution", "inst-1")]
    response = auth_client(newbie).post(
        f"{BASE}/posts/", {"body": "x", "visibility": "institution", "audience_id": "inst-1"}, format="json"
    )
    assert response.json()["error"]["code"] == "account_too_new"
    unverified = veteran("unverified@example.com", "unverified")
    type(unverified).objects.filter(pk=unverified.pk).update(email_verified_at=None)
    response = auth_client(unverified).post(
        f"{BASE}/posts/", {"body": "x", "visibility": "institution", "audience_id": "inst-1"}, format="json"
    )
    assert response.json()["error"]["code"] == "email_not_verified"


def test_rate_limits(auth_client, author):
    client = auth_client(author)
    with override_settings(UNIVERSITY={"THROTTLE_RATES": {"anonymous_post": "2/hour"}}):
        post(client, "one")
        post(client, "two")
        assert (
            client.post(
                f"{BASE}/posts/", {"body": "3", "visibility": "institution", "audience_id": "inst-1"}, format="json"
            ).status_code
            == 429
        )


def test_spam_held_for_review(auth_client, author, reader):
    held = post(auth_client(author), "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA BUY NOW EVERYONE CLICK THIS LINK RIGHT NOW")
    assert held["status"] == "pending_review"
    assert auth_client(reader).get(f"{BASE}/posts/{held['id']}/").status_code == 404
    assert auth_client(author).get(f"{BASE}/posts/{held['id']}/").status_code == 200


def test_delete_own_post_only(auth_client, author, reader):
    created = post(auth_client(author))
    assert auth_client(reader).delete(f"{BASE}/posts/{created['id']}/").status_code == 404
    assert auth_client(author).delete(f"{BASE}/posts/{created['id']}/").status_code == 204
    assert auth_client(reader).get(f"{BASE}/posts/{created['id']}/").status_code == 404


# ----------------------------------------------------------------- comments
def test_thread_pseudonyms(auth_client, author, reader, moderator):
    created = post(auth_client(author))
    url = f"{BASE}/posts/{created['id']}/comments/"
    first = auth_client(reader).post(url, {"body": "Same here"}, format="json").json()
    again = auth_client(reader).post(url, {"body": "Also this"}, format="json").json()
    op = auth_client(author).post(url, {"body": "Thanks!"}, format="json").json()
    other = auth_client(moderator).post(url, {"body": "Interesting"}, format="json").json()
    assert first["author"]["pseudonym"] == again["author"]["pseudonym"]  # stable within thread
    assert op["author"] == {"anonymous": True, "pseudonym": "OP", "is_op": True}
    assert other["author"]["pseudonym"] != first["author"]["pseudonym"]
    listing = auth_client(reader).get(url).json()["results"]
    assert [c["viewer"]["is_author"] for c in listing] == [True, True, False, False]
    assert AnonymousPost.objects.get(pk=created["id"]).comment_count == 4


def test_pseudonyms_differ_across_threads(auth_client, author, reader):
    names = set()
    for i in range(5):
        created = post(auth_client(author), f"post {i}")
        comment = auth_client(reader).post(f"{BASE}/posts/{created['id']}/comments/", {"body": "hi"}, format="json")
        names.add(comment.json()["author"]["pseudonym"])
    assert len(names) > 1


def test_delete_own_comment(auth_client, author, reader):
    created = post(auth_client(author))
    comment = auth_client(reader).post(f"{BASE}/posts/{created['id']}/comments/", {"body": "x"}, format="json").json()
    assert auth_client(author).delete(f"{BASE}/comments/{comment['id']}/").status_code == 404
    assert auth_client(reader).delete(f"{BASE}/comments/{comment['id']}/").status_code == 204


# --------------------------------------------------------- reactions / hide
def test_reactions_and_hide(auth_client, author, reader):
    created = post(auth_client(author))
    client = auth_client(reader)
    assert client.post(f"{BASE}/posts/{created['id']}/reaction/", {"kind": "support"}, format="json").status_code == 204
    detail = client.get(f"{BASE}/posts/{created['id']}/").json()
    assert detail["counts"]["reactions"] == 1 and detail["viewer"]["reaction"] == "support"
    client.post(f"{BASE}/posts/{created['id']}/hide/")
    assert client.get(f"{BASE}/posts/").json()["results"] == []
    client.delete(f"{BASE}/posts/{created['id']}/hide/")
    assert len(client.get(f"{BASE}/posts/").json()["results"]) == 1


# --------------------------------------------------------------- moderation
def test_reports_and_restrictions_apply(auth_client, author, reader, moderator):
    created = post(auth_client(author))
    report = auth_client(reader).post(
        "/api/v1/moderation/reports/",
        {"content_type": "anonymous.post", "object_id": created["id"], "reason": "harassment"},
        format="json",
    )
    assert report.status_code == 201
    from university.moderation.models import ModerationCase

    case = ModerationCase.objects.get()
    assert case.target_author is None and case.target_is_anonymous
    auth_client(moderator).post(
        f"/api/v1/moderation/cases/{case.pk}/actions/", {"action": "hide", "reason": "Targets a student"}, format="json"
    )
    assert auth_client(reader).get(f"{BASE}/posts/{created['id']}/").status_code == 404
    own = auth_client(author).get(f"{BASE}/posts/{created['id']}/").json()
    assert own["status"] == "hidden" and own["moderation_reason"] == "Targets a student"
    # The author can appeal without being identified.
    appeal = auth_client(author).post(
        "/api/v1/moderation/appeals/",
        {"content_type": "anonymous.post", "object_id": created["id"], "statement": "It was a general complaint."},
        format="json",
    )
    assert appeal.status_code == 201


def test_sanction_restricts_anonymous_posting(auth_client, author, reader, moderator):
    from university.moderation.models import ModerationCase
    from university.permissions.models import Role
    from university.permissions.services import assign_role

    created = post(auth_client(author))
    auth_client(reader).post(
        "/api/v1/moderation/reports/",
        {"content_type": "anonymous.post", "object_id": created["id"], "reason": "harassment"},
        format="json",
    )
    case = ModerationCase.objects.get()
    Role.objects.create(key="anon_sanctions", name="x", permissions=["anonymous.authors.sanction"])
    assign_role(user=moderator, role_key="anon_sanctions")
    response = auth_client(moderator).post(
        f"/api/v1/moderation/cases/{case.pk}/actions/",
        {"action": "restrict", "reason": "Repeated harassment", "duration_hours": 72, "restriction_kind": "all"},
        format="json",
    )
    assert response.status_code == 201 and response.json()["target_user"] == {"anonymous": True}
    blocked = auth_client(author).post(
        f"{BASE}/posts/", {"body": "again", "visibility": "institution", "audience_id": "inst-1"}, format="json"
    )
    assert blocked.json()["error"]["code"] == "content_creation_restricted"


# ------------------------------------------------------------------- reveal
def test_two_person_reveal(auth_client, author, reader, revealer, approver):
    created = post(auth_client(author))
    short = auth_client(revealer).post(
        f"{BASE}/reveal-requests/",
        {"kind": "post", "object_id": created["id"], "justification": "because"},
        format="json",
    )
    assert short.status_code == 400
    justification = "Court order NG/HC/2026/1234 concerning credible threats of violence."
    req = (
        auth_client(revealer)
        .post(
            f"{BASE}/reveal-requests/",
            {"kind": "post", "object_id": created["id"], "justification": justification, "case_reference": "CASE-77"},
            format="json",
        )
        .json()
    )
    assert req["status"] == "pending"
    identity_url = f"{BASE}/reveal-requests/{req['id']}/identity/"
    assert auth_client(revealer).get(identity_url).json()["error"]["code"] == "not_approved"
    # Requester cannot approve their own request even with the approve permission.
    from university.permissions.services import assign_role

    assign_role(user=revealer, role_key="reveal_approver")
    self_approve = auth_client(revealer).post(
        f"{BASE}/reveal-requests/{req['id']}/decide/", {"approve": True, "reason": "ok"}, format="json"
    )
    assert self_approve.json()["error"]["code"] == "two_person_rule"
    assert (
        auth_client(approver)
        .post(f"{BASE}/reveal-requests/{req['id']}/decide/", {"approve": True, "reason": "Valid order"}, format="json")
        .status_code
        == 200
    )
    # Only the requester can retrieve.
    assert auth_client(approver).get(identity_url).status_code in (403, 404)
    identity = auth_client(revealer).get(identity_url)
    assert identity.status_code == 200 and identity["Cache-Control"] == "no-store"
    assert identity.json()["user_id"] == str(author.pk) and identity.json()["email"] == author.email
    actions = list(AuditLog.objects.filter(action__startswith="anonymous.identity").values_list("action", flat=True))
    assert {
        "anonymous.identity.reveal_requested",
        "anonymous.identity.reveal_approved",
        "anonymous.identity.revealed",
    } <= set(actions)
    # Audit entries reference the request, never the identity.
    for entry in AuditLog.objects.filter(action__startswith="anonymous.identity"):
        assert str(author.pk) not in str(entry.metadata) and entry.target_id != str(author.pk)
    assert RevealRequest.objects.get(pk=req["id"]).retrieval_count == 1


def test_reveal_permissions_and_expiry(auth_client, author, moderator, revealer, approver):
    created = post(auth_client(author))
    payload = {"kind": "post", "object_id": created["id"], "justification": "x" * 40}
    assert auth_client(moderator).post(f"{BASE}/reveal-requests/", payload, format="json").status_code == 403
    req = auth_client(revealer).post(f"{BASE}/reveal-requests/", payload, format="json").json()
    auth_client(approver).post(
        f"{BASE}/reveal-requests/{req['id']}/decide/", {"approve": True, "reason": "ok"}, format="json"
    )
    RevealRequest.objects.filter(pk=req["id"]).update(expires_at=timezone.now() - dt.timedelta(minutes=1))
    response = auth_client(revealer).get(f"{BASE}/reveal-requests/{req['id']}/identity/")
    assert response.json()["error"]["code"] == "approval_expired"


def test_denied_reveal(auth_client, author, revealer, approver):
    created = post(auth_client(author))
    req = (
        auth_client(revealer)
        .post(
            f"{BASE}/reveal-requests/",
            {"kind": "post", "object_id": created["id"], "justification": "y" * 40},
            format="json",
        )
        .json()
    )
    auth_client(approver).post(
        f"{BASE}/reveal-requests/{req['id']}/decide/", {"approve": False, "reason": "Insufficient basis"}, format="json"
    )
    assert auth_client(revealer).get(f"{BASE}/reveal-requests/{req['id']}/identity/").status_code == 403


def test_export_and_purge(auth_client, author, reader):
    from university.core.testing import PASSWORD
    from university.users.services import delete_account, purge_user

    created = post(auth_client(author), "mine")
    post(auth_client(reader), "theirs")
    mine = auth_client(author).get("/api/v1/me/export/").json()["anonymous"]
    assert [p["body"] for p in mine["posts"]] == ["mine"]
    delete_account(author, password=PASSWORD)
    purge_user(type(author).all_objects.get(pk=author.pk))
    assert not AnonymousPost.all_objects.filter(pk=created["id"]).exists()
    assert AnonymousPost.objects.filter(body="theirs").exists()
