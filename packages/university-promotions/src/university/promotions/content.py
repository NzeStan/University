"""Content adapter: running adverts can be reported.

Moderation policy (explicit, as required before enabling reports):

* **Who investigates:** platform moderators and ads reviewers (``promotions.review``), never the
  advertiser.
* **What they may do:** hide (the campaign is paused and sent back as rejected), restore (back to
  review), or remove (rejected for good). Sanctions against the advertiser go through normal
  moderation. Boosts are reported through the boosted content itself.
"""

from __future__ import annotations

from typing import Any

from university.core.content import ContentAdapter, ContentRef
from university.core.ids import is_valid_uuid


class CampaignAdapter(ContentAdapter):
    content_type = "promotions.campaign"
    label = "Advert"
    moderatable = True

    def _get(self, object_id: Any) -> Any:
        from university.promotions.models import Campaign

        if not is_valid_uuid(object_id):
            return None
        return Campaign.objects.filter(pk=object_id).first()

    def resolve(self, object_id: Any) -> ContentRef | None:
        campaign = self._get(object_id)
        if campaign is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(campaign.pk),
            author_id=str(campaign.advertiser_id),
            excerpt=f"{campaign.headline or campaign.name}\n{campaign.body}"[:500],
            status=campaign.status,
            created_at=campaign.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        campaign = self._get(object_id)
        if campaign is None:
            return False
        if viewer is not None and getattr(viewer, "pk", None) == campaign.advertiser_id:
            return True
        return campaign.status == "active"

    def is_author(self, object_id: Any, user: Any) -> bool:
        campaign = self._get(object_id)
        return bool(campaign and user is not None and getattr(user, "pk", None) == campaign.advertiser_id)

    def resolve_author(self, object_id: Any) -> Any:
        campaign = self._get(object_id)
        return campaign.advertiser if campaign else None

    def hide(self, object_id: Any, *, reason: str) -> None:
        from university.promotions.models import Campaign

        Campaign.objects.filter(pk=object_id).update(
            status="rejected", review_note=f"Removed after reports: {reason}"[:500]
        )

    def restore(self, object_id: Any) -> None:
        from university.promotions.models import Campaign

        Campaign.objects.filter(pk=object_id, status="rejected").update(status="in_review", review_note="")

    def remove(self, object_id: Any, *, reason: str) -> None:
        self.hide(object_id, reason=reason)
