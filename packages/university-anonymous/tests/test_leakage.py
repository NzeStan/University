"""MANDATORY anonymous-identity leakage tests.

Every channel an attacker (another user, a moderator, an admin, a downstream
consumer, or someone holding a database dump) could use to link an author to
their anonymous content is probed here. A failure in this file is a privacy
incident, not a flaky test.
"""

from __future__ import annotations

import uuid

import pytest
from django.db import connection
from django.test import override_settings

from tests.helpers import BASE, identifiers, post
from university.anonymous.identity import open_identity, owner_token
from university.anonymous.models import AnonymousComment, AnonymousPost, Authorship
from university.audit.models import AuditLog
from university.core.events import event_bus

pytestmark = [pytest.mark.django_db, pytest.mark.security]


def _assert_no_identity(response, user) -> None:
    text = response.content.decode()
    for value in identifiers(user):
        assert value not in text, f"identity leaked: {value!r} in {response.request['PATH_INFO']}"


def test_api_responses_never_contain_the_author(auth_client, author, reader, moderator, superuser):
    created = post(auth_client(author))
    comment = auth_client(author).post(f"{BASE}/posts/{created['id']}/comments/", {"body": "op reply"}, format="json")
    _assert_no_identity(comment, author)
    for viewer in (reader, moderator, superuser):
        client = auth_client(viewer)
        for url in (
            f"{BASE}/posts/",
            f"{BASE}/posts/{created['id']}/",
            f"{BASE}/posts/{created['id']}/comments/",
        ):
            response = client.get(url)
            if response.status_code == 200:
                _assert_no_identity(response, author)


def test_moderation_views_never_contain_the_author(auth_client, author, reader, moderator):
    created = post(auth_client(author))
    auth_client(reader).post(
        "/api/v1/moderation/reports/",
        {"content_type": "anonymous.post", "object_id": created["id"], "reason": "spam"},
        format="json",
    )
    from university.moderation.models import ModerationCase

    case = ModerationCase.objects.get()
    for url in ("/api/v1/moderation/cases/", f"/api/v1/moderation/cases/{case.pk}/"):
        _assert_no_identity(auth_client(moderator).get(url), author)
    action = auth_client(moderator).post(
        f"/api/v1/moderation/cases/{case.pk}/actions/", {"action": "hide", "reason": "x"}, format="json"
    )
    _assert_no_identity(action, author)


def test_events_never_contain_the_author(auth_client, author, reader):
    seen = []
    event_bus.subscribe("*", seen.append)
    try:
        created = post(auth_client(author))
        auth_client(author).post(f"{BASE}/posts/{created['id']}/comments/", {"body": "c"}, format="json")
        auth_client(author).delete(f"{BASE}/posts/{created['id']}/")
    finally:
        event_bus.unsubscribe("*", seen.append)
    anonymous_events = [e for e in seen if e.name.startswith("anonymous.")]
    assert anonymous_events
    for event in anonymous_events:
        assert event.actor_id is None
        assert all(value not in str(event.payload) for value in identifiers(author))


def test_database_holds_no_plaintext_link(auth_client, author):
    first = post(auth_client(author), "one")
    second = post(auth_client(author), "two")
    # No author column anywhere on anonymous tables.
    for model in (AnonymousPost, AnonymousComment, Authorship):
        assert not any(f.is_relation and f.related_model is type(author) for f in model._meta.get_fields())
    records = list(Authorship.objects.all())
    dump = " ".join(f"{r.owner_token} {r.identity_cipher}" for r in records)
    for value in identifiers(author):
        assert value not in dump
    # Unlinkable at rest: one author's tokens and ciphertexts all differ.
    assert len({r.owner_token for r in records}) == len({r.identity_cipher for r in records}) == 2
    # ...but the platform can still prove/restore authorship with its keys.
    for record, created in zip(
        sorted(records, key=lambda r: str(r.object_id)), sorted([first, second], key=lambda p: p["id"]), strict=True
    ):
        assert record.owner_token == owner_token("post", created["id"], author.pk)
        assert open_identity(record.identity_cipher) == str(author.pk)


def test_raw_sql_dump_contains_no_author_identifiers(auth_client, author):
    post(auth_client(author), "dump me")
    with connection.cursor() as cursor:
        rows = []
        for table in (AnonymousPost._meta.db_table, AnonymousComment._meta.db_table, Authorship._meta.db_table):
            cursor.execute(f"SELECT * FROM {table}")
            rows.extend(cursor.fetchall())
    flat = " ".join(str(v) for row in rows for v in row)
    for value in identifiers(author):
        assert value not in flat


def test_audit_log_never_links_author_to_content(auth_client, author, reader):
    created = post(auth_client(author))
    auth_client(author).post(f"{BASE}/posts/{created['id']}/comments/", {"body": "c"}, format="json")
    auth_client(author).delete(f"{BASE}/posts/{created['id']}/")
    linked = AuditLog.objects.filter(actor_ref=str(author.pk), target_id=created["id"])
    assert not linked.exists()
    assert not AuditLog.objects.filter(
        actor_ref=str(author.pk), target_type__startswith="university_anonymous"
    ).exists()


def test_blocking_does_not_create_an_unmasking_oracle(auth_client, author, reader):
    """If blocks hid anonymous posts, blocking a suspect would reveal authorship."""
    from university.core.hooks import Hook, hooks

    created = post(auth_client(author))

    def everyone_blocks_everyone(viewer, target):
        return False

    hooks.register(Hook.USER_CAN_VIEW_PROFILE, everyone_blocks_everyone)
    hooks.register(Hook.USER_CAN_INTERACT, lambda actor, target, action: False)
    try:
        assert [p["id"] for p in auth_client(reader).get(f"{BASE}/posts/").json()["results"]] == [created["id"]]
    finally:
        hooks.unregister(Hook.USER_CAN_VIEW_PROFILE, everyone_blocks_everyone)
        hooks._hooks[Hook.USER_CAN_INTERACT] = [
            i for i in hooks._hooks.get(Hook.USER_CAN_INTERACT, []) if i.fn.__name__ != "<lambda>"
        ]


def test_errors_do_not_distinguish_authors_from_strangers(auth_client, author, reader):
    created = post(auth_client(author))
    missing = str(uuid.uuid4())
    for url in (f"{BASE}/posts/{created['id']}/", f"{BASE}/posts/{missing}/"):
        response = auth_client(reader).delete(url)
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Not found."
    appeal = {"content_type": "anonymous.post", "object_id": created["id"], "statement": "probe for authorship"}
    assert auth_client(reader).post("/api/v1/moderation/appeals/", appeal, format="json").status_code == 404


def test_ids_are_random_and_timestamps_coarse(auth_client, author):
    with override_settings(UNIVERSITY={"IDS": {"UUID_VERSION": 7}}):
        created = post(auth_client(author))
    assert uuid.UUID(created["id"]).version == 4
    stored = AnonymousPost.objects.get(pk=created["id"])
    assert stored.created_at.timestamp() % 300 == 0
    assert not hasattr(stored, "updated_at")


def test_other_users_exports_do_not_include_anonymous_content(auth_client, author, reader):
    post(auth_client(author), "secret thoughts")
    export = auth_client(reader).get("/api/v1/me/export/").json()
    assert export["anonymous"] == {"posts": [], "comments": []}
    assert "secret thoughts" not in str(export)


def test_viewer_flags_do_not_leak_across_users(auth_client, author, reader):
    created = post(auth_client(author))
    assert auth_client(reader).get(f"{BASE}/posts/{created['id']}/").json()["viewer"]["is_author"] is False
    assert auth_client(author).get(f"{BASE}/posts/{created['id']}/").json()["viewer"]["is_author"] is True
