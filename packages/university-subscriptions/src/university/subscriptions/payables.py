"""How payments charges for a subscription period (Core's payable contract): the platform is the payee."""

from __future__ import annotations

from typing import Any

from university.core.exceptions import NotFound
from university.core.ids import is_valid_uuid
from university.core.payables import Payable, PayableAdapter
from university.subscriptions.conf import plans
from university.subscriptions.models import Subscription


class PeriodPayable(PayableAdapter):
    purpose = "subscriptions.period"
    label = "Subscription"

    def resolve(self, object_id: Any, payer: Any) -> Payable:
        from university.subscriptions.services import amount_due

        sub = Subscription.objects.filter(pk=object_id).first() if is_valid_uuid(object_id) else None
        due = amount_due(sub) if sub is not None and sub.user_id == getattr(payer, "pk", None) else None
        if sub is None or due is None:
            raise NotFound("Nothing is due on this subscription.")
        name = plans().get(sub.plan, {}).get("name", sub.plan)
        return Payable(
            purpose=self.purpose,
            object_id=str(sub.pk),
            payer_id=str(sub.user_id),
            amount_minor=due,
            currency=sub.currency,
            description=f"{name} ({sub.get_interval_display().lower()})"[:120],
            platform_fee_minor=due,
            metadata={"subscription_id": str(sub.pk), "plan": sub.plan, "interval": sub.interval},
        )

    def on_paid(self, object_id: Any, *, reference: str, amount_minor: int, currency: str) -> None:
        from university.subscriptions.services import pay_period

        pay_period(object_id, reference=reference, amount_minor=amount_minor, currency=currency)

    def on_refunded(self, object_id: Any, *, reference: str, amount_minor: int, currency: str) -> None:
        from university.subscriptions.services import refund_period

        refund_period(reference)
