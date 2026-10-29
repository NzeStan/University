"""Profile badge, data export, purge and the scheduled sweep for subscriptions."""

from __future__ import annotations

from typing import Any

from university.core.entitlements import has_entitlement
from university.core.tasks import task
from university.subscriptions.models import Subscription


def public_profile(target: Any, viewer: Any) -> dict[str, Any]:
    # Only the badge is public; plans and payments never are.
    return {"premium": has_entitlement(target, "premium.badge")}


def export_data(user: Any) -> dict[str, Any]:
    return {
        "subscriptions": [
            {
                "id": s.pk,
                "plan": s.plan,
                "interval": s.interval,
                "status": s.status,
                "periods": [
                    {
                        "starts_at": p.starts_at,
                        "ends_at": p.ends_at,
                        "amount_minor": p.amount_minor,
                        "currency": p.currency,
                    }
                    for p in s.periods.all()
                ],
            }
            for s in Subscription.objects.filter(user=user).prefetch_related("periods")
        ]
    }


def purge(user_id: Any) -> None:
    # Payment records live (anonymised) in university-payments' ledger; the plan history goes.
    Subscription.objects.filter(user_id=user_id).delete()


@task(name="university.subscriptions.sweep")
def sweep() -> dict[str, int]:
    from university.subscriptions.services import sweep as run

    return run()
