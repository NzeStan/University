"""How payments charges for a campaign (Core's payable contract): the platform is the payee."""

from __future__ import annotations

from typing import Any

from university.core.exceptions import NotFound
from university.core.ids import is_valid_uuid
from university.core.payables import Payable, PayableAdapter
from university.promotions.models import Campaign, CampaignStatus


class CampaignPayable(PayableAdapter):
    purpose = "promotions.campaign"
    label = "Promotion campaign"

    def resolve(self, object_id: Any, payer: Any) -> Payable:
        campaign = Campaign.objects.filter(pk=object_id).first() if is_valid_uuid(object_id) else None
        if (
            campaign is None
            or campaign.advertiser_id != getattr(payer, "pk", None)
            or campaign.status != CampaignStatus.PENDING_PAYMENT
        ):
            raise NotFound("Nothing to pay for.")
        return Payable(
            purpose=self.purpose,
            object_id=str(campaign.pk),
            payer_id=str(campaign.advertiser_id),
            amount_minor=campaign.budget_minor,
            currency=campaign.currency,
            description=f"Promotion: {campaign.name}"[:120],
            platform_fee_minor=campaign.budget_minor,
            metadata={"campaign_id": str(campaign.pk), "kind": campaign.kind},
        )

    def on_paid(self, object_id: Any, *, reference: str, amount_minor: int, currency: str) -> None:
        from university.promotions.services import mark_paid

        mark_paid(object_id, reference=reference)

    def on_refunded(self, object_id: Any, *, reference: str, amount_minor: int, currency: str) -> None:
        Campaign.objects.filter(pk=object_id, status=CampaignStatus.PENDING_PAYMENT).update(status=CampaignStatus.DRAFT)
