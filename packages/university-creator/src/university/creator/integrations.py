"""Core hook implementations: public profile badge, export and purge."""

from __future__ import annotations

from typing import Any

from university.creator.constants import ProfileStatus


def public_profile(target: Any, viewer: Any) -> dict[str, Any]:
    from university.creator.models import CreatorProfile

    profile = (
        CreatorProfile.objects.filter(user=target, status=ProfileStatus.ACTIVE).prefetch_related("categories").first()
    )
    if profile is None:
        return {}
    return {
        "creator": {
            "id": str(profile.pk),
            "verified": profile.is_verified,
            "headline": profile.headline,
            "categories": [c.key for c in profile.categories.all()],
        }
    }


def export_data(user: Any) -> dict[str, Any]:
    from university.creator.models import Campaign, CreatorProfile

    profile = CreatorProfile.objects.filter(user=user).prefetch_related("categories").first()
    data: dict[str, Any] = {
        "creator_campaigns_owned": [
            {"title": c.title, "brand": c.brand_name, "status": c.status, "created_at": c.created_at.isoformat()}
            for c in Campaign.all_objects.filter(owner=user)
        ]
    }
    if profile is None:
        return data
    kit = getattr(profile, "media_kit", None)
    data["creator_profile"] = {
        "headline": profile.headline,
        "bio": profile.bio,
        "categories": [c.key for c in profile.categories.all()],
        "city": profile.city,
        "country": profile.country,
        "languages": profile.languages,
        "business_email": profile.business_email,
        "verification_status": profile.verification_status,
        "linked_accounts": [
            {"provider": a.provider, "handle": a.handle, "follower_count": a.follower_count, "ownership": a.ownership}
            for a in profile.linked_accounts.all()
        ],
        "verification_requests": [
            {"status": r.status, "statement": r.statement, "created_at": r.created_at.isoformat()}
            for r in profile.verification_requests.all()
        ],
        "media_kit": (
            {"summary": kit.summary, "audience": kit.audience, "rates": kit.rates, "highlights": kit.highlights}
            if kit
            else None
        ),
        "campaign_participations": [
            {"campaign": p.campaign.title, "status": p.status, "agreed_fee_minor": p.agreed_fee_minor}
            for p in profile.participations.select_related("campaign")
        ],
    }
    return data


def purge(user_id: Any) -> None:
    from django.db import transaction

    from university.creator.constants import CampaignStatus
    from university.creator.models import Campaign, CreatorProfile, Participation
    from university.creator.services.campaigns import _release_slot, cancel_campaign_records

    with transaction.atomic():
        # Accepted deals free their slots for the brand.
        for participation in Participation.objects.filter(profile__user_id=user_id, status="accepted"):
            campaign = Campaign.objects.select_for_update().get(pk=participation.campaign_id)
            _release_slot(campaign)
        CreatorProfile.objects.filter(user_id=user_id).delete()
        for campaign in Campaign.all_objects.select_for_update().filter(owner_id=user_id):
            if campaign.status not in (CampaignStatus.COMPLETED, CampaignStatus.CANCELLED):
                cancel_campaign_records(campaign, reason="The organiser's account was deleted.")
        Campaign.all_objects.filter(owner_id=user_id).update(owner=None)
