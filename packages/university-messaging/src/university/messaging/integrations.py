"""Data export and purge for messaging."""

from __future__ import annotations

from typing import Any

from university.messaging.models import Message, MessagingSettings, Participant


def export_data(user: Any) -> dict[str, Any]:
    sent = Message.objects.filter(sender=user).order_by("created_at")
    return {
        "messaging": {
            "conversations": [str(p.conversation_id) for p in Participant.objects.filter(user=user)],
            "messages_sent": [
                {"id": m.pk, "conversation": m.conversation_id, "body": m.text, "created_at": m.created_at}
                for m in sent
            ],
        }
    }


def purge(user_id: Any) -> None:
    """Erase what a purged person wrote; others keep their side of each conversation."""
    Message.objects.filter(sender_id=user_id).delete()
    Participant.objects.filter(user_id=user_id).delete()
    MessagingSettings.objects.filter(user_id=user_id).delete()
