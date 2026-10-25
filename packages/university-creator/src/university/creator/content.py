"""Content adapter for campaigns — moderatable, with an explicit policy.

Sponsorship briefs are a known vector for scams (fake brand deals, advance-fee
fraud), so campaigns opt in to moderation:

* **Who investigates**: ``ContentRef.scope`` is the sponsoring scope when there
  is one (its moderators), otherwise platform moderators.
* **Which actions**: ``hide`` (managers only; can't be reopened), ``restore``,
  and ``remove`` (cancels the campaign and every open or accepted
  participation, notifying creators, then soft-deletes it). User-level
  sanctions apply to the campaign owner under moderation's usual rules.

Creator profiles and media kits are not separate content types: they are part
of the person's account and are reported through the ``users.user`` adapter.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from university.core.content import ContentAdapter, ContentRef
from university.core.events import publish
from university.core.ids import is_valid_uuid
from university.creator import events
from university.creator.constants import CAMPAIGN_CONTENT_TYPE, CampaignStatus


class CampaignAdapter(ContentAdapter):
    content_type = CAMPAIGN_CONTENT_TYPE
    label = "Campaign"
    moderatable = True

    def iter_ids(self) -> Any:
        """Live items, for search backfills."""
        from university.creator.models import Campaign

        qs = Campaign.objects.filter(status=CampaignStatus.OPEN, hidden_at__isnull=True)
        return (str(pk) for pk in qs.values_list("pk", flat=True).iterator())

    def _get(self, object_id: Any) -> Any:
        from university.creator.models import Campaign

        return Campaign.objects.filter(pk=object_id).first() if is_valid_uuid(object_id) else None

    def resolve(self, object_id: Any) -> ContentRef | None:
        campaign = self._get(object_id)
        if campaign is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(campaign.pk),
            author_id=str(campaign.owner_id) if campaign.owner_id else None,
            scope=campaign.sponsor_scope,
            excerpt=f"{campaign.title}\n{campaign.brand_name}\n{campaign.brief}"[:500],
            status="hidden" if campaign.hidden_at else campaign.status,
            created_at=campaign.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        from university.creator.selectors import can_view_campaign

        campaign = self._get(object_id)
        return campaign is not None and can_view_campaign(viewer, campaign)

    def hide(self, object_id: Any, *, reason: str) -> None:
        campaign = self._get(object_id)
        if campaign is not None and campaign.hidden_at is None:
            campaign.hidden_at = timezone.now()
            campaign.hidden_reason = reason[:255]
            campaign.save(update_fields=["hidden_at", "hidden_reason", "updated_at"])
            publish(events.CAMPAIGN_HIDDEN, {"campaign_id": campaign.pk, "owner_id": campaign.owner_id})

    def restore(self, object_id: Any) -> None:
        campaign = self._get(object_id)
        if campaign is not None and campaign.hidden_at is not None:
            campaign.hidden_at = None
            campaign.hidden_reason = ""
            campaign.save(update_fields=["hidden_at", "hidden_reason", "updated_at"])

    @transaction.atomic
    def remove(self, object_id: Any, *, reason: str) -> None:
        from university.creator.services.campaigns import cancel_campaign_records

        campaign = self._get(object_id)
        if campaign is None:
            return
        if campaign.status not in (CampaignStatus.COMPLETED, CampaignStatus.CANCELLED):
            cancel_campaign_records(campaign, reason=reason or "Removed by moderators.")
        campaign.delete()
