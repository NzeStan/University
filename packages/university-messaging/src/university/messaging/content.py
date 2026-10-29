"""Content adapter: messages can be reported by the people in the conversation.

Moderation policy (explicit, as required before enabling reports):

* **Who can report:** only participants (``can_view`` is participant-only), and reporting shares
  just that one message with moderators, not the rest of the conversation.
* **Who investigates:** platform moderators (trust & safety).
* **What they may do:** hide the message (participants then see "removed by the moderators"),
  restore it, or remove it. Sanctions against the sender go through the normal moderation actions.
* Messages are never indexed for search.
"""

from __future__ import annotations

from typing import Any

from university.core.content import ContentAdapter, ContentRef
from university.core.ids import is_valid_uuid


class MessageAdapter(ContentAdapter):
    content_type = "messaging.message"
    label = "Message"
    moderatable = True

    def _get(self, object_id: Any) -> Any:
        from university.messaging.models import Message

        if not is_valid_uuid(object_id):
            return None
        return Message.objects.filter(pk=object_id).first()

    def iter_ids(self) -> Any:
        return ()

    def resolve(self, object_id: Any) -> ContentRef | None:
        from university.messaging.crypto import unseal

        message = self._get(object_id)
        if message is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(message.pk),
            author_id=str(message.sender_id) if message.sender_id else None,
            excerpt=unseal(message.body_cipher)[:500],
            status=message.status,
            created_at=message.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        from university.messaging.models import Participant, ParticipantState

        message = self._get(object_id)
        if message is None or viewer is None or not getattr(viewer, "is_authenticated", False):
            return False
        return (
            Participant.objects.filter(conversation_id=message.conversation_id, user=viewer)
            .exclude(state__in=[ParticipantState.LEFT, ParticipantState.DECLINED])
            .exists()
        )

    def is_author(self, object_id: Any, user: Any) -> bool:
        message = self._get(object_id)
        return bool(message and user is not None and message.sender_id == getattr(user, "pk", None))

    def resolve_author(self, object_id: Any) -> Any:
        message = self._get(object_id)
        return message.sender if message else None

    def hide(self, object_id: Any, *, reason: str) -> None:
        from university.messaging.models import Message

        Message.objects.filter(pk=object_id).update(status="hidden")

    def restore(self, object_id: Any) -> None:
        from university.messaging.models import Message

        Message.objects.filter(pk=object_id, status="hidden").update(status="visible")

    def remove(self, object_id: Any, *, reason: str) -> None:
        from university.messaging.models import Message

        Message.objects.filter(pk=object_id).update(status="hidden", body_cipher="")
