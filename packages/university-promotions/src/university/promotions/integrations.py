"""Data export, purge and scheduled jobs for promotions."""

from __future__ import annotations

from typing import Any

from university.core.tasks import task
from university.promotions.models import Campaign


def export_data(user: Any) -> dict[str, Any]:
    return {
        "promotions": {
            "campaigns": [
                {"id": c.pk, "name": c.name, "status": c.status, "budget_minor": c.budget_minor, "currency": c.currency}
                for c in Campaign.objects.filter(advertiser=user)
            ]
        }
    }


def purge(user_id: Any) -> None:
    for campaign in Campaign.objects.filter(advertiser_id=user_id):
        if campaign.image:
            campaign.image.delete(save=False)
        campaign.delete()


@task(name="university.promotions.complete_finished")
def complete_finished() -> int:
    from university.promotions.services import complete_finished as run

    return run()
