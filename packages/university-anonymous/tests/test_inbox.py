"""Anonymous inboxes: turning one on, sending, answering, blocking, moderation and reveal."""

from __future__ import annotations

import pytest

from tests.conftest import veteran
from tests.helpers import BASE
from university.anonymous.models import AnonymousMessage, Authorship, BlockedSender
from university.core.events import event_bus
from university.core.testing import create_user

pytestmark = pytest.mark.django_db
INBOX = f"{BASE}/me/inbox/"


@pytest.fixture
def owner(db):
    return veteran("owner@example.com", "owner", member=False)


def open_inbox(client, prompt="Ask me anything about campus life"):
    response = client.patch(INBOX, {"enabled": True, "prompt": prompt}, format="json")
    assert response.status_code == 200, response.json()
    return response.json()


def send(client, handle="owner", body="What's your favourite spot on campus?"):
    return client.post(f"{BASE}/inboxes/{handle}/messages/", {"body": body}, format="json")


def received(client):
    return client.get(f"{INBOX}messages/").json()["results"]


def test_inbox_is_off_until_its_owner_turns_it_on(auth_client, api_client, owner, author):
    assert auth_client(owner).get(INBOX).json()["enabled"] is False
    assert api_client.get(f"{BASE}/inboxes/owner/").status_code == 404
    assert send(auth_client(author)).status_code == 404
    assert open_inbox(auth_client(owner))["enabled"] is True
    public = api_client.get(f"{BASE}/inboxes/owner/").json()
    assert public["prompt"] == "Ask me anything about campus life" and public["owner"]["handle"] == "owner"
    auth_client(owner).patch(INBOX, {"enabled": False}, format="json")
    assert api_client.get(f"{BASE}/inboxes/owner/").status_code == 404


def test_sending_and_reading(auth_client, owner, author):
    open_inbox(auth_client(owner))
    response = send(auth_client(author))
    assert response.status_code == 202 and response.json() == {"detail": "Sent anonymously."}
    messages = received(auth_client(owner))
    assert len(messages) == 1 and messages[0]["body"] == "What's your favourite spot on campus?"
    assert messages[0]["read_at"] is None
    assert auth_client(owner).get(INBOX).json()["unread_count"] == 1
    auth_client(owner).post(f"{INBOX}messages/{messages[0]['id']}/read/")
    assert auth_client(owner).get(INBOX).json()["unread_count"] == 0
    # Nobody else can read someone's inbox.
    assert auth_client(author).get(f"{INBOX}messages/").json()["results"] == []


def test_sender_gates(auth_client, owner, author):
    open_inbox(auth_client(owner))
    newbie = create_user("new@example.com", handle="newbie")
    assert send(auth_client(newbie)).json()["error"]["code"] == "account_too_new"
    assert send(auth_client(owner)).json()["error"]["code"] == "own_inbox"
    assert send(auth_client(author), body="   ").status_code == 400
    assert send(auth_client(author), body="x" * 1001).status_code == 400


def test_rate_limited_per_inbox(auth_client, owner, author):
    open_inbox(auth_client(owner))
    codes = [send(auth_client(author), body=f"Question {i}").status_code for i in range(4)]
    assert codes == [202, 202, 202, 429]


@pytest.mark.security
def test_blocking_whoever_sent_this_drops_their_future_messages_silently(auth_client, owner, author, reader):
    open_inbox(auth_client(owner))
    send(auth_client(author), body="mean message")
    send(auth_client(reader), body="kind message")
    mean = next(m for m in received(auth_client(owner)) if m["body"] == "mean message")
    assert auth_client(owner).post(f"{INBOX}messages/{mean['id']}/block-sender/").status_code == 204
    assert [m["body"] for m in received(auth_client(owner))] == ["kind message"]
    # The blocked sender is told it was sent, but it never arrives.
    assert send(auth_client(author), body="again").status_code == 202
    assert [m["body"] for m in received(auth_client(owner))] == ["kind message"]
    # Others are unaffected; the owner only sees a count, never who.
    assert send(auth_client(reader), body="kind again").status_code == 202
    assert auth_client(owner).get(INBOX).json()["blocked_senders"] == 1
    assert len(received(auth_client(owner))) == 2


@pytest.mark.security
def test_profile_blocks_drop_messages_silently(auth_client, owner, author):
    from university.core.hooks import Hook, hooks

    open_inbox(auth_client(owner))

    def blocked(actor, target, action):
        return False if action == "anonymous_message" else None

    hooks.register(Hook.USER_CAN_INTERACT, blocked)
    try:
        assert send(auth_client(author)).status_code == 202
    finally:
        hooks.unregister(Hook.USER_CAN_INTERACT, blocked)
    assert received(auth_client(owner)) == []


def test_answers_can_be_public_and_taken_back(auth_client, api_client, owner, author):
    open_inbox(auth_client(owner))
    send(auth_client(author), body="Best jollof on campus?")
    message = received(auth_client(owner))[0]
    url = f"{INBOX}messages/{message['id']}/answer/"
    private = auth_client(owner).post(url, {"answer": "Mama Put by the library."}, format="json").json()
    assert private["answer_public"] is False
    assert api_client.get(f"{BASE}/inboxes/owner/answers/").json()["results"] == []
    auth_client(owner).post(url, {"answer": "Mama Put by the library.", "public": True}, format="json")
    answers = api_client.get(f"{BASE}/inboxes/owner/answers/").json()["results"]
    assert answers == [
        {
            "id": message["id"],
            "question": "Best jollof on campus?",
            "answer": "Mama Put by the library.",
            "answered_at": answers[0]["answered_at"],
        }
    ]
    assert api_client.get(f"{BASE}/inboxes/owner/").json()["answers_count"] == 1
    auth_client(owner).delete(url)
    assert api_client.get(f"{BASE}/inboxes/owner/answers/").json()["results"] == []


def test_recipient_can_delete_and_report(auth_client, owner, author, moderator):
    open_inbox(auth_client(owner))
    send(auth_client(author), body="threatening message")
    message = received(auth_client(owner))[0]
    report = auth_client(owner).post(
        "/api/v1/moderation/reports/",
        {"content_type": "anonymous.message", "object_id": message["id"], "reason": "harassment"},
        format="json",
    )
    assert report.status_code in (200, 201, 202), report.json()
    from university.moderation.models import ModerationCase

    case = ModerationCase.objects.get(content_type="anonymous.message")
    hide = auth_client(moderator).post(
        f"/api/v1/moderation/cases/{case.pk}/actions/", {"action": "hide", "reason": "Threat"}, format="json"
    )
    assert hide.status_code in (200, 201), hide.json()
    assert received(auth_client(owner)) == []
    # Deleting is the recipient's own choice too.
    send(auth_client(author), body="another one")
    other = received(auth_client(owner))[0]
    assert auth_client(owner).delete(f"{INBOX}messages/{other['id']}/").status_code == 204
    assert received(auth_client(owner)) == []


def test_messages_follow_the_two_person_reveal(auth_client, owner, author, revealer, approver):
    open_inbox(auth_client(owner))
    send(auth_client(author), body="threat")
    message = AnonymousMessage.objects.get()
    request = (
        auth_client(revealer)
        .post(
            f"{BASE}/reveal-requests/",
            {
                "kind": "message",
                "object_id": str(message.pk),
                "justification": "Police request NG/2026/88: threats to a student.",
            },
            format="json",
        )
        .json()
    )
    assert request["status"] == "pending"
    auth_client(approver).post(
        f"{BASE}/reveal-requests/{request['id']}/decide/", {"approve": True, "reason": "Valid request"}, format="json"
    )
    identity = auth_client(revealer).get(f"{BASE}/reveal-requests/{request['id']}/identity/").json()
    assert identity["handle"] == "secretauthor"


def test_purge_and_export(auth_client, owner, author):
    from university.anonymous.integrations import export_data, purge

    open_inbox(auth_client(owner))
    send(auth_client(author), body="exported question")
    assert export_data(author)["anonymous"]["messages_sent"][0]["body"] == "exported question"
    assert export_data(owner)["anonymous"]["messages_received"][0]["body"] == "exported question"
    purge(author.pk)
    assert not AnonymousMessage.all_objects.exists() and not Authorship.objects.filter(kind="message").exists()
    send(auth_client(veteran("x@example.com", "xavier", member=False)), body="for the owner")
    purge(owner.pk)
    assert not AnonymousMessage.all_objects.exists() and not BlockedSender.objects.exists()


@pytest.mark.security
def test_received_event_names_the_recipient_only(auth_client, owner, author):
    seen = []
    event_bus.subscribe("anonymous.message.received", seen.append)
    try:
        open_inbox(auth_client(owner))
        send(auth_client(author))
    finally:
        event_bus.unsubscribe("anonymous.message.received", seen.append)
    assert len(seen) == 1 and set(seen[0].payload) == {"message_id", "recipient_id"}
    assert seen[0].actor_id is None and str(author.pk) not in str(seen[0].payload)


@pytest.mark.security
def test_only_the_recipient_can_see_a_private_message(auth_client, owner, author, reader):
    from university.anonymous.content import AnonymousMessageAdapter

    open_inbox(auth_client(owner))
    send(auth_client(author), body="private question")
    message = AnonymousMessage.objects.get()
    adapter = AnonymousMessageAdapter()
    assert adapter.can_view(owner, message.pk) is True
    assert adapter.can_view(author, message.pk) is False  # Not even the sender, who'd otherwise confirm it.
    assert adapter.can_view(reader, message.pk) is False
    assert adapter.can_view(None, message.pk) is False
    # Strangers can't reach it through reporting either.
    probe = auth_client(reader).post(
        "/api/v1/moderation/reports/",
        {"content_type": "anonymous.message", "object_id": str(message.pk), "reason": "spam"},
        format="json",
    )
    assert probe.status_code == 404
    # Once answered publicly, anyone may see it.
    auth_client(owner).post(f"{INBOX}messages/{message.pk}/answer/", {"answer": "Sure", "public": True}, format="json")
    assert adapter.can_view(reader, message.pk) is True
