"""Content adapter for events — moderatable, with an explicit policy.

Events are user-generated (titles, descriptions, links) and a known vector for
scams and spam, so they opt in to moderation. The policy:

* **Who investigates**: ``ContentRef.scope`` is the event's host scope, so
  reports about an event hosted by a community or institution go to that
  scope's moderators; personal events go to platform moderators.
* **Which actions**: ``hide`` (visible to organizers only, can't be
  published), ``restore``, and ``remove`` (cancels the event, tells
  attendees, then soft-deletes it). User-level sanctions apply to the
  event's creator through moderation's usual rules.
* Organizers can't moderate their own event (moderation's conflict-of-interest
  guard uses :meth:`is_author`).
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from university.core.content import ContentAdapter, ContentRef
from university.core.events import publish
from university.core.ids import is_valid_uuid
from university.events import events
from university.events.constants import CONTENT_TYPE, EventStatus


class EventAdapter(ContentAdapter):
    content_type = CONTENT_TYPE
    label = "Event"
    moderatable = True

    def iter_ids(self) -> Any:
        """Live items, for search backfills."""
        from university.events.models import Event

        qs = Event.objects.filter(status=EventStatus.PUBLISHED, hidden_at__isnull=True)
        return (str(pk) for pk in qs.values_list("pk", flat=True).iterator())

    def _get(self, object_id: Any) -> Any:
        from university.events.models import Event

        return Event.objects.filter(pk=object_id).first() if is_valid_uuid(object_id) else None

    def resolve(self, object_id: Any) -> ContentRef | None:
        event = self._get(object_id)
        if event is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(event.pk),
            author_id=str(event.created_by_id) if event.created_by_id else None,
            scope=event.host_scope,
            excerpt=f"{event.title}\n{event.summary}"[:500],
            status="hidden" if event.hidden_at else event.status,
            created_at=event.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        from university.events.selectors import can_view

        event = self._get(object_id)
        return event is not None and can_view(viewer, event)

    def hide(self, object_id: Any, *, reason: str) -> None:
        event = self._get(object_id)
        if event is not None and event.hidden_at is None:
            event.hidden_at = timezone.now()
            event.hidden_reason = reason[:255]
            event.save(update_fields=["hidden_at", "hidden_reason", "updated_at"])
            publish(events.EVENT_HIDDEN, {"event_id": event.pk})

    def restore(self, object_id: Any) -> None:
        event = self._get(object_id)
        if event is not None and event.hidden_at is not None:
            event.hidden_at = None
            event.hidden_reason = ""
            event.save(update_fields=["hidden_at", "hidden_reason", "updated_at"])

    @transaction.atomic
    def remove(self, object_id: Any, *, reason: str) -> None:
        from university.events.services.hosting import cancel_event_records

        event = self._get(object_id)
        if event is None:
            return
        if event.status != EventStatus.CANCELLED:
            cancel_event_records(event, reason or "Removed by moderators.")
        event.delete()
