"""Messaging: requests, conversations, groups, privacy, blocks, encryption and moderation."""

from __future__ import annotations

import datetime as dt

import pytest
from django.db import connection
from django.utils import timezone

from university.core.events import event_bus
from university.core.hooks import Hook, hooks
from university.core.testing import create_user
from university.messaging.models import Message

pytestmark = pytest.mark.django_db
BASE = "/api/v1/messaging"


def start(client, *users, body="Hey! Are you going to the hackathon?", **extra):
    response = client.post(
        f"{BASE}/conversations/", {"participant_ids": [str(u.pk) for u in users], "body": body, **extra}, format="json"
    )
    assert response.status_code == 201, response.json()
    return response.json()


def folder(client, name="inbox"):
    return client.get(f"{BASE}/conversations/", {"folder": name}).json()["results"]


def thread(client, conversation_id):
    return client.get(f"{BASE}/conversations/{conversation_id}/messages/").json()["results"]


def test_first_messages_from_strangers_are_requests(auth_client, user, other_user):
    convo = start(auth_client(user), other_user)
    assert [c["id"] for c in folder(auth_client(user))] == [convo["id"]]
    assert folder(auth_client(other_user)) == []
    requests = folder(auth_client(other_user), "requests")
    assert [c["id"] for c in requests] == [convo["id"]] and requests[0]["state"] == "request"
    assert requests[0]["participants"][0]["handle"] == user.handle
    assert auth_client(other_user).get(f"{BASE}/unread/").json()["requests"] == 1
    # Replying accepts the request.
    auth_client(other_user).post(f"{BASE}/conversations/{convo['id']}/messages/", {"body": "Yes!"}, format="json")
    assert [c["id"] for c in folder(auth_client(other_user))] == [convo["id"]]
    # Once they talk, the next conversation isn't a request.
    third = create_user("third@example.com", handle="third")
    group = start(auth_client(user), other_user, third, title="Hackathon team")
    assert [c["id"] for c in folder(auth_client(other_user)) if c["id"] == group["id"]]


def test_direct_conversations_are_reused(auth_client, user, other_user):
    first = start(auth_client(user), other_user)
    second = start(auth_client(user), other_user, body="Following up")
    assert first["id"] == second["id"]
    assert len(thread(auth_client(user), first["id"])) == 2


def test_unread_counts_and_reading(auth_client, user, other_user):
    convo = start(auth_client(user), other_user)
    auth_client(other_user).post(f"{BASE}/conversations/{convo['id']}/accept/")
    for body in ("one", "two"):
        auth_client(user).post(f"{BASE}/conversations/{convo['id']}/messages/", {"body": body}, format="json")
    assert folder(auth_client(other_user))[0]["unread_count"] == 3
    assert auth_client(other_user).get(f"{BASE}/unread/").json() == {"conversations": 1, "messages": 3, "requests": 0}
    auth_client(other_user).post(f"{BASE}/conversations/{convo['id']}/read/")
    assert folder(auth_client(other_user))[0]["unread_count"] == 0
    assert folder(auth_client(user))[0]["last_message"]["body"] == "two"


@pytest.mark.security
def test_outsiders_cannot_read_or_post(auth_client, user, other_user):
    convo = start(auth_client(user), other_user)
    stranger = create_user("s@example.com", handle="stranger")
    assert auth_client(stranger).get(f"{BASE}/conversations/{convo['id']}/").status_code == 404
    assert auth_client(stranger).get(f"{BASE}/conversations/{convo['id']}/messages/").status_code == 404
    response = auth_client(stranger).post(
        f"{BASE}/conversations/{convo['id']}/messages/", {"body": "hi"}, format="json"
    )
    assert response.status_code == 404


@pytest.mark.security
def test_blocks_and_closed_requests_look_the_same(auth_client, user, other_user):
    def blocked(actor, target, action):
        return False if action == "message" else None

    hooks.register(Hook.USER_CAN_INTERACT, blocked)
    try:
        response = auth_client(user).post(
            f"{BASE}/conversations/", {"participant_ids": [str(other_user.pk)], "body": "hi"}, format="json"
        )
    finally:
        hooks.unregister(Hook.USER_CAN_INTERACT, blocked)
    auth_client(other_user).patch(f"{BASE}/settings/", {"allow_requests": False}, format="json")
    closed = auth_client(user).post(
        f"{BASE}/conversations/", {"participant_ids": [str(other_user.pk)], "body": "hi"}, format="json"
    )
    assert response.status_code == closed.status_code == 403
    assert response.json()["error"]["message"] == closed.json()["error"]["message"] == "You can't message this person."


@pytest.mark.security
def test_message_text_is_encrypted_at_rest(auth_client, user, other_user):
    start(auth_client(user), other_user, body="my secret exam answers")
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT body_cipher FROM {Message._meta.db_table}")
        stored = " ".join(row[0] for row in cursor.fetchall())
    assert "secret" not in stored and stored.startswith("gAAAA")
    assert Message.objects.get().text == "my secret exam answers"


@pytest.mark.security
def test_events_never_carry_message_text(auth_client, user, other_user):
    seen = []
    event_bus.subscribe("*", seen.append)
    try:
        start(auth_client(user), other_user, body="confidential plans")
    finally:
        event_bus.unsubscribe("*", seen.append)
    messaging_events = [e for e in seen if e.name.startswith("messaging.")]
    assert {e.name for e in messaging_events} == {"messaging.request.received", "messaging.message.sent"}
    assert all("confidential" not in str(e.payload) for e in messaging_events)


def test_edit_window_and_delete_for_everyone(auth_client, user, other_user):
    convo = start(auth_client(user), other_user)
    message_id = thread(auth_client(user), convo["id"])[0]["id"]
    assert (
        auth_client(other_user).patch(f"{BASE}/messages/{message_id}/", {"body": "hacked"}, format="json").status_code
        == 404
    )
    edited = auth_client(user).patch(f"{BASE}/messages/{message_id}/", {"body": "Edited"}, format="json").json()
    assert edited["body"] == "Edited" and edited["edited_at"]
    Message.objects.filter(pk=message_id).update(created_at=timezone.now() - dt.timedelta(hours=1))
    late = auth_client(user).patch(f"{BASE}/messages/{message_id}/", {"body": "again"}, format="json")
    assert late.json()["error"]["code"] == "edit_window_closed"
    deleted = auth_client(user).delete(f"{BASE}/messages/{message_id}/").json()
    assert deleted["status"] == "deleted" and deleted["body"] == "This message was deleted."
    assert Message.objects.get(pk=message_id).body_cipher == ""  # Erased, not just hidden.


def test_groups(auth_client, user, other_user):
    third, fourth = create_user("t@example.com", handle="third"), create_user("f@example.com", handle="fourth")
    group = start(auth_client(user), other_user, third, title="Study group")
    assert group["kind"] == "group" and group["title"] == "Study group" and group["is_admin"] is True
    assert len(group["participants"]) == 2
    response = auth_client(other_user).post(
        f"{BASE}/conversations/{group['id']}/participants/", {"user_ids": [str(fourth.pk)]}, format="json"
    )
    assert response.json()["error"]["code"] == "not_group_admin"
    auth_client(user).post(
        f"{BASE}/conversations/{group['id']}/participants/", {"user_ids": [str(fourth.pk)]}, format="json"
    )
    assert len(auth_client(user).get(f"{BASE}/conversations/{group['id']}/").json()["participants"]) == 3
    auth_client(user).post(f"{BASE}/conversations/{group['id']}/leave/")
    assert auth_client(user).get(f"{BASE}/conversations/{group['id']}/").status_code == 404


def test_mute_and_archive(auth_client, user, other_user):
    convo = start(auth_client(user), other_user)
    auth_client(user).patch(f"{BASE}/conversations/{convo['id']}/", {"archived": True, "muted": True}, format="json")
    assert folder(auth_client(user)) == []
    assert folder(auth_client(user), "archived")[0]["muted"] is True
    # A new message brings it back to the inbox.
    auth_client(other_user).post(f"{BASE}/conversations/{convo['id']}/messages/", {"body": "ping"}, format="json")
    assert [c["id"] for c in folder(auth_client(user))] == [convo["id"]]


def test_sending_is_rate_limited(auth_client, user, other_user, settings):
    settings.UNIVERSITY = {"THROTTLE_RATES": {"messaging_new_conversation": "1/day"}}
    start(auth_client(user), other_user)
    third = create_user("t@example.com", handle="third")
    assert (
        auth_client(user)
        .post(f"{BASE}/conversations/", {"participant_ids": [str(third.pk)], "body": "hi"}, format="json")
        .status_code
        == 429
    )


def test_only_participants_can_report_and_moderators_see_one_message(auth_client, user, other_user):
    from university.messaging.content import MessageAdapter

    convo = start(auth_client(user), other_user, body="abusive message")
    message = Message.objects.get()
    adapter = MessageAdapter()
    assert adapter.moderatable and adapter.can_view(other_user, message.pk)
    assert not adapter.can_view(create_user("s@example.com", handle="stranger"), message.pk)
    assert adapter.resolve(message.pk).excerpt == "abusive message"
    adapter.hide(message.pk, reason="Harassment")
    body = thread(auth_client(other_user), convo["id"])[0]["body"]
    assert body == "This message was removed by the moderators."
    assert adapter.resolve(message.pk).excerpt == "abusive message"  # Moderators can still review it.


def test_unverified_emails_cannot_message(auth_client, other_user):
    newbie = create_user("n@example.com", handle="newbie", verified=False)
    response = auth_client(newbie).post(
        f"{BASE}/conversations/", {"participant_ids": [str(other_user.pk)], "body": "hi"}, format="json"
    )
    assert response.json()["error"]["code"] == "email_not_verified"


def test_purge_and_export(auth_client, user, other_user):
    from university.messaging.integrations import export_data, purge

    convo = start(auth_client(user), other_user, body="exported")
    auth_client(other_user).post(f"{BASE}/conversations/{convo['id']}/messages/", {"body": "reply"}, format="json")
    assert export_data(user)["messaging"]["messages_sent"][0]["body"] == "exported"
    purge(user.pk)
    assert [m["body"] for m in thread(auth_client(other_user), convo["id"])] == ["reply"]
