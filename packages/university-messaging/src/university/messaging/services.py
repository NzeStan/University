"""Messaging. Every mutation checks membership, blocks and rate limits, and publishes ids-only events.

Protection against unwanted messages:

* A conversation someone new starts with you lands in **Requests** until you accept (or reply).
  You can turn requests off entirely.
* Blocks stop messaging. "Blocked" and "not accepting requests" give the **same** answer, so a block
  is never revealed.
* Starting conversations and sending messages are rate limited.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from university.core.content import ensure_can_create
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.hooks import Hook, hooks
from university.core.ratelimit import rate_limit
from university.messaging import events
from university.messaging.conf import messaging_settings as conf
from university.messaging.models import (
    Conversation,
    ConversationKind,
    Message,
    MessageStatus,
    MessagingSettings,
    Participant,
    ParticipantState,
)

CANNOT_MESSAGE = "You can't message this person."


def settings_for(user: Any) -> MessagingSettings:
    return MessagingSettings.objects.get_or_create(user=user)[0]


def update_settings(user: Any, *, allow_requests: bool) -> MessagingSettings:
    obj = settings_for(user)
    obj.allow_requests = allow_requests
    obj.save(update_fields=["allow_requests", "updated_at"])
    return obj


def _gate(user: Any) -> None:
    if conf.get("REQUIRE_VERIFIED_EMAIL", True) and not user.email_verified_at:
        raise PermissionDenied("Verify your email address to send messages.", code="email_not_verified")
    ensure_can_create(user, "messaging.message")


def _text(body: str) -> str:
    body = (body or "").strip()
    if not body:
        raise ValidationError(details={"body": ["Write a message."]})
    limit = int(conf.get("MESSAGE_MAX_LENGTH", 4000))
    if len(body) > limit:
        raise ValidationError(details={"body": [f"Keep it under {limit} characters."]})
    return body


def _can_contact(sender: Any, recipient: Any) -> bool:
    return recipient.is_active and hooks.allows(Hook.USER_CAN_INTERACT, sender, recipient, "message")


def membership(user: Any, conversation_id: Any) -> Participant:
    participant = (
        Participant.objects.select_related("conversation")
        .filter(conversation_id=conversation_id, user=user)
        .exclude(state__in=[ParticipantState.LEFT, ParticipantState.DECLINED])
        .first()
    )
    if participant is None:
        raise NotFound()
    return participant


def _users(ids: Iterable[Any], sender: Any) -> list[Any]:
    wanted = {str(i) for i in ids} - {str(sender.pk)}
    users = list(get_user_model().objects.filter(pk__in=wanted, status="active"))
    if len(users) != len(wanted):
        raise ValidationError(details={"participant_ids": ["Someone in this list can't be found."]})
    return users


def _invite_state(sender: Any, recipient: Any) -> str:
    """New conversations are requests unless the recipient already talks to the sender."""
    talks = Participant.objects.filter(
        user=recipient, state=ParticipantState.ACTIVE, conversation__participants__user=sender
    ).exists()
    return ParticipantState.ACTIVE if talks else ParticipantState.REQUEST


@transaction.atomic
def start_conversation(
    *, sender: Any, participant_ids: list[Any], body: str, title: str = ""
) -> tuple[Conversation, Message]:
    _gate(sender)
    recipients = _users(participant_ids, sender)
    if not recipients:
        raise ValidationError(details={"participant_ids": ["Choose who to message."]})
    if len(recipients) + 1 > int(conf.get("MAX_GROUP_SIZE", 50)):
        raise ValidationError(details={"participant_ids": ["That's too many people for one conversation."]})
    body = _text(body)
    for recipient in recipients:
        if not _can_contact(sender, recipient):
            raise PermissionDenied(CANNOT_MESSAGE, code="cannot_message")
    if len(recipients) == 1:
        recipient = recipients[0]
        key = ":".join(sorted([str(sender.pk), str(recipient.pk)]))
        existing = Conversation.objects.filter(direct_key=key).first()
        if existing is not None:
            mine = Participant.objects.filter(conversation=existing, user=sender).first()
            if mine and mine.state in (ParticipantState.LEFT, ParticipantState.DECLINED):
                mine.state = ParticipantState.ACTIVE
                mine.save(update_fields=["state", "updated_at"])
            return existing, send_message(sender=sender, conversation_id=existing.pk, body=body)
        state = _invite_state(sender, recipient)
        if state == ParticipantState.REQUEST and not settings_for(recipient).allow_requests:
            raise PermissionDenied(CANNOT_MESSAGE, code="cannot_message")
        rate_limit("messaging_new_conversation", key=str(sender.pk))
        try:
            with transaction.atomic():
                conversation = Conversation.objects.create(
                    kind=ConversationKind.DIRECT, created_by=sender, direct_key=key
                )
        except IntegrityError:  # Created concurrently: use that one.
            conversation = Conversation.objects.get(direct_key=key)
            return conversation, send_message(sender=sender, conversation_id=conversation.pk, body=body)
        Participant.objects.create(
            conversation=conversation, user=sender, state=ParticipantState.ACTIVE, last_read_at=timezone.now()
        )
        Participant.objects.create(conversation=conversation, user=recipient, state=state)
    else:
        rate_limit("messaging_new_conversation", key=str(sender.pk))
        conversation = Conversation.objects.create(
            kind=ConversationKind.GROUP, created_by=sender, title=title.strip()[:100]
        )
        Participant.objects.create(
            conversation=conversation,
            user=sender,
            is_admin=True,
            state=ParticipantState.ACTIVE,
            last_read_at=timezone.now(),
        )
        for recipient in recipients:
            state = _invite_state(sender, recipient)
            if state == ParticipantState.REQUEST and not settings_for(recipient).allow_requests:
                raise PermissionDenied(CANNOT_MESSAGE, code="cannot_message")
            Participant.objects.create(conversation=conversation, user=recipient, state=state)
    for participant in conversation.participants.filter(state=ParticipantState.REQUEST):
        publish(
            events.REQUEST_RECEIVED,
            {"conversation_id": conversation.pk, "sender_id": sender.pk, "recipient_id": participant.user_id},
        )
    return conversation, send_message(
        sender=sender, conversation_id=conversation.pk, body=body, announce_requests=False
    )


@transaction.atomic
def send_message(
    *, sender: Any, conversation_id: Any, body: str, reply_to: Any = None, announce_requests: bool = True
) -> Message:
    _gate(sender)
    mine = membership(sender, conversation_id)
    conversation = mine.conversation
    others = list(
        conversation.participants.exclude(user=sender)
        .exclude(state__in=[ParticipantState.LEFT, ParticipantState.DECLINED])
        .select_related("user")
    )
    if conversation.kind == ConversationKind.DIRECT and (not others or not _can_contact(sender, others[0].user)):
        raise PermissionDenied(CANNOT_MESSAGE, code="cannot_message")
    rate_limit("messaging_message", key=str(sender.pk))
    body = _text(body)
    reply = None
    if reply_to:
        reply = Message.objects.filter(pk=reply_to, conversation=conversation).first()
        if reply is None:
            raise ValidationError(details={"reply_to": ["That message isn't in this conversation."]})
    message = Message(conversation=conversation, sender=sender, reply_to=reply)
    message.text = body
    message.save()
    now = message.created_at
    Conversation.objects.filter(pk=conversation.pk).update(last_message_at=now)
    if mine.state == ParticipantState.REQUEST:  # Replying accepts the request.
        mine.state = ParticipantState.ACTIVE
    mine.last_read_at = now
    mine.archived = False
    mine.save(update_fields=["state", "last_read_at", "archived", "updated_at"])
    Participant.objects.filter(conversation=conversation, archived=True).exclude(user=sender).update(archived=False)
    recipients = [p.user_id for p in others if p.state == ParticipantState.ACTIVE and not p.muted]
    publish(
        events.MESSAGE_SENT,
        {
            "message_id": message.pk,
            "conversation_id": conversation.pk,
            "sender_id": sender.pk,
            "recipient_ids": recipients,
        },
        actor=sender,
    )
    return message


def respond_to_request(*, user: Any, conversation_id: Any, accept: bool) -> Participant:
    participant = membership(user, conversation_id)
    if participant.state != ParticipantState.REQUEST:
        raise Conflict("This isn't a message request.", code="not_a_request")
    participant.state = ParticipantState.ACTIVE if accept else ParticipantState.DECLINED
    participant.save(update_fields=["state", "updated_at"])
    return participant


def mark_read(*, user: Any, conversation_id: Any) -> Participant:
    participant = membership(user, conversation_id)
    participant.last_read_at = timezone.now()
    participant.save(update_fields=["last_read_at", "updated_at"])
    return participant


def update_participation(
    *, user: Any, conversation_id: Any, muted: bool | None = None, archived: bool | None = None
) -> Participant:
    participant = membership(user, conversation_id)
    if muted is not None:
        participant.muted = muted
    if archived is not None:
        participant.archived = archived
    participant.save(update_fields=["muted", "archived", "updated_at"])
    return participant


@transaction.atomic
def rename(*, user: Any, conversation_id: Any, title: str) -> Conversation:
    participant = membership(user, conversation_id)
    if participant.conversation.kind != ConversationKind.GROUP or not participant.is_admin:
        raise PermissionDenied("Only group admins can rename a group.", code="not_group_admin")
    participant.conversation.title = title.strip()[:100]
    participant.conversation.save(update_fields=["title", "updated_at"])
    return participant.conversation


@transaction.atomic
def add_participants(*, user: Any, conversation_id: Any, user_ids: list[Any]) -> Conversation:
    participant = membership(user, conversation_id)
    conversation = participant.conversation
    if conversation.kind != ConversationKind.GROUP or not participant.is_admin:
        raise PermissionDenied("Only group admins can add people.", code="not_group_admin")
    newcomers = [
        u
        for u in _users(user_ids, user)
        if not conversation.participants.filter(user=u).exclude(state=ParticipantState.LEFT).exists()
    ]
    if conversation.participants.exclude(state__in=[ParticipantState.LEFT, ParticipantState.DECLINED]).count() + len(
        newcomers
    ) > int(conf.get("MAX_GROUP_SIZE", 50)):
        raise ValidationError(details={"user_ids": ["The group would be too big."]})
    for newcomer in newcomers:
        if not _can_contact(user, newcomer):
            raise PermissionDenied(CANNOT_MESSAGE, code="cannot_message")
        state = _invite_state(user, newcomer)
        Participant.objects.update_or_create(
            conversation=conversation, user=newcomer, defaults={"state": state, "is_admin": False}
        )
        if state == ParticipantState.REQUEST:
            publish(
                events.REQUEST_RECEIVED,
                {"conversation_id": conversation.pk, "sender_id": user.pk, "recipient_id": newcomer.pk},
            )
    return conversation


def leave(*, user: Any, conversation_id: Any) -> None:
    participant = membership(user, conversation_id)
    participant.state = ParticipantState.LEFT
    participant.save(update_fields=["state", "updated_at"])
    conversation = participant.conversation
    if participant.is_admin and conversation.kind == ConversationKind.GROUP:
        successor = conversation.participants.filter(state=ParticipantState.ACTIVE).order_by("created_at").first()
        if successor and not conversation.participants.filter(state=ParticipantState.ACTIVE, is_admin=True).exists():
            successor.is_admin = True
            successor.save(update_fields=["is_admin", "updated_at"])


def _own_message(user: Any, message_id: Any) -> Message:
    message = Message.objects.select_related("conversation").filter(pk=message_id, sender=user).first()
    if message is None or message.status != MessageStatus.VISIBLE:
        raise NotFound()
    membership(user, message.conversation_id)
    return message


def edit_message(*, user: Any, message_id: Any, body: str) -> Message:
    message = _own_message(user, message_id)
    window = int(conf.get("EDIT_WINDOW_MINUTES", 15))
    if (timezone.now() - message.created_at).total_seconds() > window * 60:
        raise Conflict(f"Messages can only be edited for {window} minutes.", code="edit_window_closed")
    message.text = _text(body)
    message.edited_at = timezone.now()
    message.save(update_fields=["body_cipher", "edited_at", "updated_at"])
    return message


def delete_message(*, user: Any, message_id: Any) -> Message:
    """Delete for everyone: the text is erased immediately; a tombstone keeps the thread readable."""
    message = _own_message(user, message_id)
    message.status = MessageStatus.DELETED
    message.body_cipher = ""
    message.deleted_at = timezone.now()
    message.save(update_fields=["status", "body_cipher", "deleted_at", "updated_at"])
    return message
