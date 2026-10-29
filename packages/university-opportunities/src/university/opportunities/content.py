"""Content adapter: opportunities can be shown, searched and **reported**.

Moderation policy (explicit, as required before enabling reports):

* **Who investigates:** platform moderators holding ``opportunities.moderate`` (trust & safety),
  never the poster or their organisation.
* **What they may do:** hide a posting (it disappears from discovery and applications stop),
  restore it, or remove it. Sanctions against the poster go through the normal moderation
  actions (warn, restrict, suspend) with their own permissions.
* **Why reportable:** fake jobs and "pay to apply" scams target students; reports are the
  fastest signal.
"""

from __future__ import annotations

from typing import Any

from university.core.content import ContentAdapter, ContentRef
from university.core.ids import is_valid_uuid


class OpportunityAdapter(ContentAdapter):
    content_type = "opportunities.opportunity"
    label = "Opportunity"
    moderatable = True

    def _get(self, object_id: Any) -> Any:
        from university.opportunities.models import Opportunity

        if not is_valid_uuid(object_id):
            return None
        return Opportunity.all_objects.filter(pk=object_id).first()

    def iter_ids(self) -> Any:
        from university.opportunities.models import Opportunity

        live = Opportunity.objects.filter(status="open", is_hidden=False, audience="public").values_list(
            "pk", flat=True
        )
        return (str(pk) for pk in live.iterator())

    def resolve(self, object_id: Any) -> ContentRef | None:
        opportunity = self._get(object_id)
        if opportunity is None or opportunity.deleted_at:
            return None
        scope = ("institution", opportunity.scope_id) if opportunity.audience == "institution" else None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(opportunity.pk),
            author_id=str(opportunity.poster_id),
            scope=scope,
            excerpt=f"{opportunity.title} at {opportunity.organization_name}\n{opportunity.description}"[:500],
            status="hidden" if opportunity.is_hidden else opportunity.status,
            created_at=opportunity.published_at or opportunity.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        from university.opportunities.selectors import can_view

        opportunity = self._get(object_id)
        return opportunity is not None and not opportunity.deleted_at and can_view(viewer, opportunity)

    def is_author(self, object_id: Any, user: Any) -> bool:
        opportunity = self._get(object_id)
        return bool(opportunity and user is not None and getattr(user, "pk", None) == opportunity.poster_id)

    def resolve_author(self, object_id: Any) -> Any:
        opportunity = self._get(object_id)
        return opportunity.poster if opportunity else None

    def hide(self, object_id: Any, *, reason: str) -> None:
        from university.core.events import publish
        from university.opportunities import events
        from university.opportunities.models import Opportunity

        Opportunity.objects.filter(pk=object_id).update(is_hidden=True, moderation_reason=reason[:255])
        publish(events.OPPORTUNITY_HIDDEN, {"opportunity_id": object_id})

    def restore(self, object_id: Any) -> None:
        from university.opportunities.models import Opportunity

        Opportunity.all_objects.filter(pk=object_id).update(is_hidden=False, moderation_reason="", deleted_at=None)

    def remove(self, object_id: Any, *, reason: str) -> None:
        opportunity = self._get(object_id)
        if opportunity is not None:
            opportunity.moderation_reason = reason[:255]
            opportunity.save(update_fields=["moderation_reason", "updated_at"])
            opportunity.delete()
