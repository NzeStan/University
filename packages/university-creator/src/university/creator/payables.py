"""Sponsorship fees, sold through Core's payable contract (no payments import).

The brand pays an accepted creator's agreed fee as ``creator.participation``.
The money is held in escrow for the creator and released when the brand marks
the collaboration completed; if the deal is cancelled after payment, the brand
is refunded. Both requests travel as events.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from university.core.exceptions import Conflict, NotFound
from university.core.ids import is_valid_uuid
from university.core.payables import Payable, PayableAdapter
from university.creator.conf import creator_settings
from university.creator.constants import ParticipationStatus
from university.creator.models import Participation

PURPOSE = "creator.participation"


class ParticipationPayable(PayableAdapter):
    purpose = PURPOSE
    label = "Sponsorship fee"

    def resolve(self, object_id: Any, payer: Any) -> Payable:
        from university.creator.selectors import can_manage_campaign

        participation = (
            Participation.objects.select_related("campaign", "profile").filter(pk=object_id).first()
            if is_valid_uuid(object_id)
            else None
        )
        if participation is None or not can_manage_campaign(payer, participation.campaign):
            raise NotFound("Participation not found.")
        if participation.status != ParticipationStatus.ACCEPTED or not participation.agreed_fee_minor:
            raise Conflict("Only accepted collaborations with an agreed fee can be paid.", code="not_payable")
        if participation.fee_paid_at:
            raise Conflict("This fee was already paid.", code="already_paid")
        amount = participation.agreed_fee_minor
        fee = amount * int(creator_settings.get("PLATFORM_FEE_BPS", 0)) // 10000
        return Payable(
            purpose=PURPOSE,
            object_id=str(participation.pk),
            payer_id=str(payer.pk),
            amount_minor=amount,
            currency=participation.campaign.currency,
            description=f"Sponsorship: {participation.campaign.title}"[:200],
            payee_id=str(participation.profile.user_id),
            platform_fee_minor=fee,
            escrow=True,
            metadata={"campaign_id": str(participation.campaign_id)},
        )

    @transaction.atomic
    def on_paid(self, object_id: Any, *, reference: str, amount_minor: int, currency: str) -> None:
        participation = Participation.objects.select_for_update().filter(pk=object_id).first()
        if participation is None or participation.status != ParticipationStatus.ACCEPTED or participation.fee_paid_at:
            raise Conflict("This collaboration can't be paid now.", code="not_payable")
        participation.fee_paid_at = timezone.now()
        participation.payment_reference = reference[:64]
        participation.save(update_fields=["fee_paid_at", "payment_reference", "updated_at"])
