"""Read side: conversation lists with unread counts and previews."""

from __future__ import annotations

from typing import Any

from django.db.models import Count, F, OuterRef, Q, QuerySet, Subquery

from university.messaging.models import Message, MessageStatus, Participant, ParticipantState

FOLDERS = {
    "inbox": Q(state=ParticipantState.ACTIVE, archived=False),
    "requests": Q(state=ParticipantState.REQUEST),
    "archived": Q(state=ParticipantState.ACTIVE, archived=True),
}


def _unread_q(user: Any) -> Q:
    return (
        Q(conversation__messages__status=MessageStatus.VISIBLE)
        & ~Q(conversation__messages__sender=user)
        & (Q(last_read_at__isnull=True) | Q(conversation__messages__created_at__gt=F("last_read_at")))
    )


def participations(user: Any, folder: str = "inbox") -> QuerySet[Participant]:
    last = Message.objects.filter(conversation=OuterRef("conversation")).order_by("-created_at")
    return (
        Participant.objects.filter(user=user)
        .filter(FOLDERS.get(folder, FOLDERS["inbox"]))
        .exclude(conversation__last_message_at__isnull=True)
        .select_related("conversation")
        .annotate(unread=Count("conversation__messages", filter=_unread_q(user), distinct=True))
        .annotate(last_message_id=Subquery(last.values("pk")[:1]))
        .order_by("-conversation__last_message_at")
    )


def unread_totals(user: Any) -> dict[str, int]:
    rows = list(participations(user, "inbox").values_list("unread", flat=True))
    return {
        "conversations": sum(1 for n in rows if n),
        "messages": sum(rows),
        "requests": Participant.objects.filter(user=user, state=ParticipantState.REQUEST).count(),
    }


def messages(conversation_id: Any) -> QuerySet[Message]:
    return (
        Message.objects.filter(conversation_id=conversation_id).select_related("sender").order_by("-created_at", "-id")
    )
