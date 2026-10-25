"""Read-side rules for creators and campaigns."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db.models import Q, QuerySet

from university.core.exceptions import NotFound
from university.core.ids import is_valid_uuid
from university.creator.constants import (
    CampaignStatus,
    CampaignVisibility,
    ProfileStatus,
    VerificationStatus,
)
from university.creator.models import Campaign, CreatorProfile, Participation
from university.permissions.scopes import Scope
from university.permissions.services import has_permission


def _authenticated(user: Any) -> bool:
    return bool(getattr(user, "is_authenticated", False))


# ----------------------------------------------------------------- profiles
def can_view_profile(viewer: Any, profile: CreatorProfile) -> bool:
    """A creator page follows the user's own privacy settings and blocks."""
    from university.users.selectors import can_view_profile as user_visible

    if _authenticated(viewer) and viewer.pk == profile.user_id:
        return True
    if profile.status != ProfileStatus.ACTIVE:
        return False
    return user_visible(viewer, profile.user)


def get_profile(lookup: Any) -> CreatorProfile:
    qs = CreatorProfile.objects.select_related("user").prefetch_related("categories")
    if is_valid_uuid(lookup):
        profile = qs.filter(Q(pk=lookup) | Q(user_id=lookup)).first()
    else:
        profile = qs.filter(user__handle=str(lookup).lower().lstrip("@")).first()
    if profile is None:
        raise NotFound("Creator not found.")
    return profile


def get_visible_profile(viewer: Any, lookup: Any) -> CreatorProfile:
    profile = get_profile(lookup)
    if not can_view_profile(viewer, profile):
        raise NotFound("Creator not found.")
    return profile


def own_profile(user: Any) -> CreatorProfile:
    profile = CreatorProfile.objects.filter(user=user).prefetch_related("categories").first()
    if profile is None:
        raise NotFound("You don't have a creator profile yet.")
    return profile


def discover(params: Mapping[str, Any]) -> QuerySet[CreatorProfile]:
    """Discoverable creators whose account profile is public and searchable.

    Blocks are applied per page by the view (they depend on the viewer).
    """
    qs = (
        CreatorProfile.objects.filter(
            status=ProfileStatus.ACTIVE,
            is_discoverable=True,
            user__is_active=True,
            user__privacy_settings__profile_visibility="public",
            user__privacy_settings__searchable=True,
        )
        .select_related("user")
        .prefetch_related("categories")
    )
    if q := (params.get("q") or "").strip()[:100]:
        qs = qs.filter(
            Q(headline__icontains=q) | Q(user__display_name__icontains=q) | Q(user__handle__icontains=q.lower())
        )
    if category := params.get("category"):
        qs = qs.filter(categories__key=category)
    if country := params.get("country"):
        qs = qs.filter(country__iexact=country)
    if str(params.get("verified", "")).lower() in ("1", "true", "yes"):
        qs = qs.filter(verification_status=VerificationStatus.VERIFIED)
    if str(params.get("open_to_sponsorships", "")).lower() in ("1", "true", "yes"):
        qs = qs.filter(open_to_sponsorships=True)
    try:
        if min_reach := int(params.get("min_reach") or 0):
            qs = qs.filter(verified_reach__gte=min_reach)
    except ValueError:
        pass
    return qs.distinct().order_by("-verified_reach", "-verified_at", "created_at")


# ---------------------------------------------------------------- campaigns
def can_manage_campaign(user: Any, campaign: Campaign) -> bool:
    if not _authenticated(user):
        return False
    if campaign.owner_id == user.pk:
        return True
    scope = Scope(*campaign.sponsor_scope) if campaign.sponsor_scope else None
    return has_permission(user, "creator.campaigns.manage", scope)


def participation_for(user: Any, campaign: Campaign) -> Participation | None:
    if not _authenticated(user):
        return None
    return Participation.objects.filter(campaign=campaign, profile__user=user).first()


def can_view_campaign(user: Any, campaign: Campaign) -> bool:
    if campaign.deleted_at is not None:
        return False
    if can_manage_campaign(user, campaign):
        return True
    if campaign.hidden_at is not None or campaign.status == CampaignStatus.DRAFT:
        return False
    if campaign.visibility == CampaignVisibility.PUBLIC:
        return True
    return participation_for(user, campaign) is not None  # Invite-only: participants.


def get_campaign(campaign_id: Any) -> Campaign:
    campaign = Campaign.objects.filter(pk=campaign_id).first() if is_valid_uuid(campaign_id) else None
    if campaign is None:
        raise NotFound("Campaign not found.")
    return campaign


def get_visible_campaign(user: Any, campaign_id: Any) -> Campaign:
    campaign = get_campaign(campaign_id)
    if not can_view_campaign(user, campaign):
        raise NotFound("Campaign not found.")
    return campaign


def open_campaigns(params: Mapping[str, Any]) -> QuerySet[Campaign]:
    qs = Campaign.objects.filter(
        status=CampaignStatus.OPEN, visibility=CampaignVisibility.PUBLIC, hidden_at__isnull=True
    ).prefetch_related("categories")
    if q := (params.get("q") or "").strip()[:100]:
        qs = qs.filter(Q(title__icontains=q) | Q(brand_name__icontains=q))
    if category := params.get("category"):
        qs = qs.filter(categories__key=category)
    return qs.distinct().order_by("-published_at", "id")


def managed_campaigns(user: Any) -> QuerySet[Campaign]:
    return Campaign.objects.filter(owner=user).order_by("-created_at")


def my_participations(user: Any) -> QuerySet[Participation]:
    return (
        Participation.objects.filter(profile__user=user, campaign__deleted_at__isnull=True)
        .select_related("campaign")
        .order_by("-updated_at")
    )
