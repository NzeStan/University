"""Data export and purge for opportunities."""

from __future__ import annotations

from typing import Any

from university.opportunities.models import Application, Opportunity, SavedOpportunity


def export_data(user: Any) -> dict[str, Any]:
    return {
        "opportunities": {
            "posted": [
                {
                    "id": o.pk,
                    "title": o.title,
                    "organization": o.organization_name,
                    "status": o.status,
                    "created_at": o.created_at,
                }
                for o in Opportunity.all_objects.filter(poster=user)
            ],
            "applications": [
                {
                    "id": a.pk,
                    "opportunity": a.opportunity_id,
                    "cover_note": a.cover_note,
                    "status": a.status,
                    "created_at": a.created_at,
                }
                for a in Application.objects.filter(applicant=user)
            ],
        }
    }


def purge(user_id: Any) -> None:
    for application in Application.objects.filter(applicant_id=user_id):
        if application.resume:
            application.resume.delete(save=False)
        application.delete()
    for opportunity in Opportunity.all_objects.filter(poster_id=user_id):
        for application in opportunity.applications.all():
            if application.resume:
                application.resume.delete(save=False)
        opportunity.hard_delete()
    SavedOpportunity.objects.filter(user_id=user_id).delete()
