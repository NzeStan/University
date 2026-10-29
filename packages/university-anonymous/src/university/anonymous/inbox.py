"""Anonymous inboxes: people turn on an inbox and others message them without revealing who they are.

Safety model (the same accountability as anonymous posts):

* Senders must pass the anonymous-posting gates (verified email, account age, no restriction).
* Authorship is stored only as a sealed identity (:class:`~university.anonymous.models.Authorship`,
  kind ``message``): reveal follows the audited two-person process, and moderators can act on
  reported messages exactly as on anonymous posts.
* Blocks are honoured **silently**: a sender the recipient has blocked (on their profile, or via
  "block whoever sent this") gets the same "sent" answer, and the message is dropped. Nothing tells
  either side who was blocked.
* Only the recipient sees messages, unless they publish an answer (the question stays anonymous).
* No audit entry, event or log line ever links a sender to a message.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from university.anonymous import events
from university.anonymous.conf import anonymous_settings
from university.anonymous.identity import sender_token
from university.anonymous.models import AnonymousInbox, AnonymousMessage, Authorship, BlockedSender, ContentStatus
from university.anonymous.services import _gate, _record_authorship, _screen, _text
from university.core.events import publish
from university.core.exceptions import NotFound, PermissionDenied, ValidationError
from university.core.hooks import Hook, hooks
from university.core.ratelimit import rate_limit


def _enabled() -> None:
    if not anonymous_settings.get("INBOX_ENABLED", True):
        raise NotFound()


def get_inbox(user: Any) -> AnonymousInbox:
    _enabled()
    inbox, _ = AnonymousInbox.objects.get_or_create(
        user=user, defaults={"prompt": anonymous_settings.get("INBOX_DEFAULT_PROMPT", "")}
    )
    return inbox


def update_inbox(user: Any, *, enabled: bool | None = None, prompt: str | None = None) -> AnonymousInbox:
    inbox = get_inbox(user)
    if enabled is not None:
        inbox.enabled = enabled
    if prompt is not None:
        inbox.prompt = prompt.strip()[:200]
    inbox.save(update_fields=["enabled", "prompt", "updated_at"])
    return inbox


def open_inbox_for(owner: Any) -> AnonymousInbox:
    """The inbox others may write to (404 when it's off or the owner is unavailable)."""
    _enabled()
    inbox = AnonymousInbox.objects.filter(user=owner, enabled=True, user__status="active").first()
    if inbox is None:
        raise NotFound()
    return inbox


@transaction.atomic
def send_message(*, sender: Any, owner: Any, body: str) -> None:
    """Deliver an anonymous message. Returns nothing: the sender learns only that it was "sent"."""
    inbox = open_inbox_for(owner)
    if sender.pk == owner.pk:
        raise ValidationError("You can't send an anonymous message to yourself.", code="own_inbox")
    _gate(sender, "anonymous.message")
    rate_limit("anonymous_message", key=f"{sender.pk}:{inbox.pk}")
    rate_limit("anonymous_message_daily", key=str(sender.pk))
    body = _text(body, int(anonymous_settings.get("MESSAGE_MAX_LENGTH", 1000)))
    token = sender_token(inbox.pk, sender.pk)
    blocked = BlockedSender.objects.filter(inbox=inbox, sender_token=token).exists() or not hooks.allows(
        Hook.USER_CAN_INTERACT, sender, owner, "anonymous_message"
    )
    if blocked:
        return  # Silently dropped: the response is identical, so neither block is revealed.
    status = _screen(body, sender, "anonymous.message")
    message = AnonymousMessage.objects.create(inbox=inbox, body=body, sender_token=token, status=status)
    _record_authorship(Authorship.Kind.MESSAGE, message.pk, sender)
    if status == ContentStatus.PUBLISHED:
        publish(events.MESSAGE_RECEIVED, {"message_id": message.pk, "recipient_id": owner.pk})


def _own_message(owner: Any, message_id: Any) -> AnonymousMessage:
    message = AnonymousMessage.objects.filter(pk=message_id, inbox__user=owner).first()
    if message is None:
        raise NotFound()
    return message


def mark_read(*, owner: Any, message_id: Any) -> AnonymousMessage:
    message = _own_message(owner, message_id)
    if message.read_at is None:
        message.read_at = timezone.now()
        AnonymousMessage.objects.filter(pk=message.pk).update(read_at=message.read_at)
    return message


@transaction.atomic
def answer(*, owner: Any, message_id: Any, text: str, public: bool) -> AnonymousMessage:
    message = _own_message(owner, message_id)
    if message.status != ContentStatus.PUBLISHED:
        raise PermissionDenied("This message can't be answered.", code="message_unavailable")
    message.answer = _text(text, int(anonymous_settings.get("ANSWER_MAX_LENGTH", 2000)))
    message.answer_public = bool(public)
    message.answered_at = timezone.now()
    message.read_at = message.read_at or message.answered_at
    message.save(update_fields=["answer", "answer_public", "answered_at", "read_at"])
    if message.answer_public:
        publish(events.MESSAGE_ANSWERED, {"message_id": message.pk, "recipient_id": owner.pk})
    return message


def unpublish_answer(*, owner: Any, message_id: Any) -> AnonymousMessage:
    message = _own_message(owner, message_id)
    AnonymousMessage.objects.filter(pk=message.pk).update(answer_public=False)
    message.answer_public = False
    return message


def delete_message(*, owner: Any, message_id: Any) -> None:
    """The recipient removes a message from their inbox (kept for moderation if it was reported)."""
    _own_message(owner, message_id).delete()


def block_sender(*, owner: Any, message_id: Any) -> None:
    """Block whoever sent this message from this inbox, without learning who they are."""
    message = _own_message(owner, message_id)
    try:
        with transaction.atomic():
            BlockedSender.objects.create(inbox=message.inbox, sender_token=message.sender_token)
    except IntegrityError:
        pass  # Already blocked.
    message.delete()


def unblock_all(owner: Any) -> int:
    return BlockedSender.objects.filter(inbox__user=owner).delete()[0]
