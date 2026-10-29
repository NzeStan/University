"""Promotions: advertisers pay a budget, reviewers approve, and the platform delivers impressions.

Integrity and privacy rules:

* Nothing runs before a reviewer approves it, and boosts can only promote the advertiser's own
  content that the viewer could see anyway.
* Served items carry a **signed token**; impressions and clicks count only with a valid token,
  once per token, so counts (and spend) can't be forged or inflated.
* Frequency capping uses short-lived keyed hashes in the cache. No viewer is stored: delivery
  statistics are daily aggregates per campaign.
* Every promoted item is labelled "Sponsored" by the API, never left to the client to decide.
"""

from __future__ import annotations

import datetime as dt
import secrets
from typing import Any

from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from university.audit.services import record as audit
from university.core.audiences import member_scopes_by_type
from university.core.crypto import keyed_hash
from university.core.entitlements import has_entitlement
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.payables import REFUND_REQUESTED
from university.core.registry import registry
from university.core.uploads import FileUploadValidator
from university.permissions.services import authorize
from university.promotions import events
from university.promotions.conf import promotions_settings as conf
from university.promotions.models import Campaign, CampaignKind, CampaignStatus, DailyStat

PURPOSE = "promotions.campaign"
TOKEN_SALT = "university.promotions.delivery"  # noqa: S105 - a signing namespace, not a secret
EDITABLE = (
    "name", "kind", "content_type", "object_id", "headline", "body", "call_to_action", "destination_url",
    "institution_ids", "placements", "starts_at", "ends_at", "budget_minor", "currency",
)  # fmt: skip


def _payload(campaign: Campaign) -> dict[str, Any]:
    return {"campaign_id": campaign.pk, "advertiser_id": campaign.advertiser_id}


def _own(actor: Any, campaign_id: Any) -> Campaign:
    campaign = Campaign.objects.filter(pk=campaign_id, advertiser=actor).first()
    if campaign is None:
        raise NotFound()
    return campaign


def _validate(actor: Any, data: dict[str, Any]) -> None:
    errors: dict[str, list[str]] = {}
    if data["kind"] == CampaignKind.BOOST:
        content_type = data.get("content_type", "")
        if content_type not in conf.get("BOOSTABLE", {}):
            errors["content_type"] = ["This can't be boosted."]
        else:
            adapter = registry.content_adapters.get(content_type)
            if (
                adapter is None
                or not adapter.is_author(data.get("object_id"), actor)
                or not adapter.can_view(None, data.get("object_id"))
            ):
                errors["object_id"] = ["You can only boost your own public content."]
    else:
        if not data.get("headline"):
            errors["headline"] = ["Write a headline."]
        url = data.get("destination_url") or ""
        if not url.startswith("https://"):
            errors["destination_url"] = ["Use a secure https:// link."]
    placements = data.get("placements") or []
    if not placements or any(p not in conf.get("PLACEMENTS", []) for p in placements):
        errors["placements"] = [f"Choose from: {', '.join(conf.get('PLACEMENTS', []))}."]
    if data["ends_at"] <= data["starts_at"]:
        errors["ends_at"] = ["Must be after the start."]
    if data["ends_at"] <= timezone.now():
        errors["ends_at"] = ["Must be in the future."]
    currency = data.get("currency", "NGN")
    if currency not in conf.get("CPM_MINOR", {}):
        errors["currency"] = ["Unsupported currency."]
    elif data["budget_minor"] < int(conf.get("MIN_BUDGET_MINOR", {}).get(currency, 0)):
        errors["budget_minor"] = ["The budget is below the minimum."]
    if errors:
        raise ValidationError(details=errors)


@transaction.atomic
def create_campaign(*, actor: Any, data: dict[str, Any]) -> Campaign:
    data = {k: v for k, v in data.items() if k in EDITABLE}
    data.setdefault("currency", "NGN")
    _validate(actor, data)
    campaign = Campaign.objects.create(advertiser=actor, cpm_minor=int(conf.get("CPM_MINOR")[data["currency"]]), **data)
    audit("promotions.campaign.created", actor=actor, target=campaign)
    return campaign


@transaction.atomic
def update_campaign(*, actor: Any, campaign_id: Any, data: dict[str, Any]) -> Campaign:
    campaign = _own(actor, campaign_id)
    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.REJECTED):
        raise Conflict("Only drafts can be edited.", code="not_editable")
    merged = {**{f: getattr(campaign, f) for f in EDITABLE}, **{k: v for k, v in data.items() if k in EDITABLE}}
    _validate(actor, merged)
    for field, value in merged.items():
        setattr(campaign, field, value)
    campaign.cpm_minor = int(conf.get("CPM_MINOR")[campaign.currency])
    campaign.status = CampaignStatus.DRAFT
    campaign.save()
    return campaign


def set_image(*, actor: Any, campaign_id: Any, file: Any) -> Campaign:
    campaign = _own(actor, campaign_id)
    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.REJECTED):
        raise Conflict("Only drafts can be edited.", code="not_editable")
    validator = FileUploadValidator(
        allowed_mime_types=conf.get("IMAGE_MIME_TYPES"), max_bytes=int(conf.get("IMAGE_MAX_BYTES"))
    )
    try:
        validator(file)
    except DjangoValidationError as exc:
        raise ValidationError(details={"file": exc.messages}) from None
    old = campaign.image.name if campaign.image else None
    campaign._upload_file = file
    campaign.image.save(file.name, file, save=True)
    if old:
        campaign.image.storage.delete(old)
    return campaign


@transaction.atomic
def submit(*, actor: Any, campaign_id: Any) -> Campaign:
    campaign = _own(actor, campaign_id)
    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.REJECTED):
        raise Conflict("This campaign was already submitted.", code="already_submitted")
    _validate(actor, {f: getattr(campaign, f) for f in EDITABLE})
    paid = bool(campaign.payment_reference)
    campaign.status = (
        CampaignStatus.PENDING_PAYMENT if conf.get("REQUIRE_PAYMENT", True) and not paid else CampaignStatus.IN_REVIEW
    )
    campaign.review_note = ""
    campaign.save(update_fields=["status", "review_note", "updated_at"])
    audit("promotions.campaign.submitted", actor=actor, target=campaign)
    if campaign.status == CampaignStatus.IN_REVIEW:
        publish(events.CAMPAIGN_SUBMITTED, _payload(campaign), actor=actor)
    return campaign


def mark_paid(campaign_id: Any, *, reference: str) -> None:
    with transaction.atomic():
        campaign = Campaign.objects.select_for_update().filter(pk=campaign_id).first()
        if campaign is None or campaign.status != CampaignStatus.PENDING_PAYMENT:
            raise Conflict("This campaign isn't awaiting payment.", code="not_payable")
        campaign.status = CampaignStatus.IN_REVIEW
        campaign.payment_reference = reference[:64]
        campaign.save(update_fields=["status", "payment_reference", "updated_at"])
    publish(events.CAMPAIGN_SUBMITTED, _payload(campaign))


@transaction.atomic
def review(*, actor: Any, campaign_id: Any, approve: bool, note: str = "") -> Campaign:
    authorize(actor, "promotions.review")
    campaign = Campaign.objects.select_for_update().filter(pk=campaign_id).first()
    if campaign is None:
        raise NotFound()
    if campaign.status != CampaignStatus.IN_REVIEW:
        raise Conflict("This campaign isn't waiting for review.", code="not_in_review")
    if campaign.advertiser_id == actor.pk:
        raise PermissionDenied("You can't review your own campaign.", code="own_campaign")
    campaign.status = CampaignStatus.ACTIVE if approve else CampaignStatus.REJECTED
    campaign.review_note = (note or "").strip()[:500]
    campaign.reviewed_by = actor
    campaign.reviewed_at = timezone.now()
    campaign.save(update_fields=["status", "review_note", "reviewed_by", "reviewed_at", "updated_at"])
    audit("promotions.campaign.reviewed", actor=actor, target=campaign, metadata={"approved": approve})
    publish(events.CAMPAIGN_REVIEWED, {**_payload(campaign), "approved": approve}, actor=actor)
    if not approve and campaign.payment_reference:
        # Rejected after payment: refund in full, then clear the reference so a resubmission pays again.
        publish(REFUND_REQUESTED, {"purpose": PURPOSE, "object_id": str(campaign.pk), "reason": "rejected"})
        Campaign.objects.filter(pk=campaign.pk).update(payment_reference="")
    return campaign


def set_paused(*, actor: Any, campaign_id: Any, paused: bool) -> Campaign:
    campaign = _own(actor, campaign_id)
    allowed = CampaignStatus.ACTIVE if paused else CampaignStatus.PAUSED
    if campaign.status != allowed:
        raise Conflict("That isn't possible for this campaign now.", code="invalid_state")
    campaign.status = CampaignStatus.PAUSED if paused else CampaignStatus.ACTIVE
    campaign.save(update_fields=["status", "updated_at"])
    return campaign


# ------------------------------------------------------------------ delivery
def _viewer_key(viewer: Any, fingerprint: str) -> str:
    base = (
        f"user:{viewer.pk}"
        if viewer is not None and getattr(viewer, "is_authenticated", False)
        else f"anon:{fingerprint}"
    )
    return keyed_hash(base, purpose="promotions-viewer")[:32]


def _frequency_key(viewer_key: str, campaign_id: Any) -> str:
    return f"promo:freq:{timezone.localdate().isoformat()}:{campaign_id}:{viewer_key}"


def eligible(viewer: Any, placement: str) -> list[Campaign]:
    now = timezone.now()
    qs = Campaign.objects.filter(status=CampaignStatus.ACTIVE, starts_at__lte=now, ends_at__gt=now).select_related(
        "advertiser"
    )
    institutions = set()
    if viewer is not None and getattr(viewer, "is_authenticated", False):
        institutions = {str(i) for i in member_scopes_by_type(viewer).get("institution", [])}
    if conf.get("AD_FREE_ENTITLEMENT") and has_entitlement(viewer, conf.get("AD_FREE_ENTITLEMENT")):
        # Premium members don't see adverts; boosted posts still show, as normal content.
        qs = qs.filter(kind=CampaignKind.BOOST)
    out = []
    for campaign in qs.order_by("?")[:50]:
        if placement not in (campaign.placements or []):
            continue
        if campaign.impressions >= campaign.impression_cap:
            continue
        if campaign.institution_ids and not institutions.intersection(str(i) for i in campaign.institution_ids):
            continue
        if campaign.kind == CampaignKind.BOOST:
            adapter = registry.content_adapters.get(campaign.content_type)
            if adapter is None or not adapter.can_view(viewer, campaign.object_id):
                continue
        out.append(campaign)
    return out


def serve(*, viewer: Any, placement: str, fingerprint: str = "") -> list[tuple[Campaign, str]]:
    """Up to MAX_ITEMS_PER_REQUEST campaigns for this viewer, each with a signed delivery token."""
    if placement not in conf.get("PLACEMENTS", []):
        raise ValidationError(details={"placement": ["Unknown placement."]})
    viewer_key = _viewer_key(viewer, fingerprint)
    cap = int(conf.get("DAILY_FREQUENCY_CAP", 3))
    served: list[tuple[Campaign, str]] = []
    for campaign in eligible(viewer, placement):
        if len(served) >= int(conf.get("MAX_ITEMS_PER_REQUEST", 3)):
            break
        if int(cache.get(_frequency_key(viewer_key, campaign.pk)) or 0) >= cap:
            continue
        token = signing.dumps({"c": str(campaign.pk), "v": viewer_key, "n": secrets.token_urlsafe(9)}, salt=TOKEN_SALT)
        served.append((campaign, token))
    return served


def _redeem(token: str, kind: str) -> tuple[Campaign, str] | None:
    try:
        data = signing.loads(token, salt=TOKEN_SALT, max_age=int(conf.get("TOKEN_MAX_AGE_SECONDS", 21600)))
    except signing.BadSignature:
        raise ValidationError(details={"token": ["Invalid or expired token."]}) from None
    # Each token counts once per kind (an impression, a click), however often it's replayed.
    if not cache.add(
        f"promo:{kind}:{keyed_hash(token, purpose='promotions-token')[:40]}",
        1,
        timeout=int(conf.get("TOKEN_MAX_AGE_SECONDS", 21600)),
    ):
        return None
    campaign = Campaign.objects.filter(pk=data["c"]).first()
    if campaign is None:
        return None
    return campaign, data["v"]


def _bump_daily(campaign: Campaign, field: str) -> None:
    today = timezone.localdate()
    stat, _ = DailyStat.objects.get_or_create(campaign=campaign, date=today)
    DailyStat.objects.filter(pk=stat.pk).update(**{field: F(field) + 1})


def record_impression(token: str) -> bool:
    redeemed = _redeem(token, "impression")
    if redeemed is None:
        return False
    campaign, viewer_key = redeemed
    if campaign.status != CampaignStatus.ACTIVE:
        return False
    freq = _frequency_key(viewer_key, campaign.pk)
    cache.add(freq, 0, timeout=26 * 60 * 60)
    cache.incr(freq)
    Campaign.objects.filter(pk=campaign.pk).update(impressions=F("impressions") + 1)
    _bump_daily(campaign, "impressions")
    campaign.refresh_from_db(fields=["impressions"])
    if campaign.impressions >= campaign.impression_cap:
        Campaign.objects.filter(pk=campaign.pk, status=CampaignStatus.ACTIVE).update(status=CampaignStatus.COMPLETED)
        publish(events.CAMPAIGN_COMPLETED, _payload(campaign))
    return True


def record_click(token: str) -> Campaign | None:
    redeemed = _redeem(token, "click")
    if redeemed is None:
        return None
    campaign, _ = redeemed
    Campaign.objects.filter(pk=campaign.pk).update(clicks=F("clicks") + 1)
    _bump_daily(campaign, "clicks")
    return campaign


def complete_finished() -> int:
    """Mark campaigns whose schedule ended as completed. Safe to run often."""
    finished = list(
        Campaign.objects.filter(status__in=[CampaignStatus.ACTIVE, CampaignStatus.PAUSED], ends_at__lte=timezone.now())
    )
    for campaign in finished:
        Campaign.objects.filter(pk=campaign.pk).update(status=CampaignStatus.COMPLETED)
        publish(events.CAMPAIGN_COMPLETED, _payload(campaign))
    return len(finished)


def stats(*, actor: Any, campaign_id: Any, days: int = 30) -> dict[str, Any]:
    campaign = _own(actor, campaign_id)
    since = timezone.localdate() - dt.timedelta(days=days - 1)
    daily = campaign.daily_stats.filter(date__gte=since).order_by("date")
    return {
        "impressions": campaign.impressions,
        "clicks": campaign.clicks,
        "click_through_rate": round(campaign.clicks / campaign.impressions, 4) if campaign.impressions else 0.0,
        "spent_minor": campaign.spent_minor,
        "budget_minor": campaign.budget_minor,
        "currency": campaign.currency,
        "daily": [{"date": d.date, "impressions": d.impressions, "clicks": d.clicks} for d in daily],
    }
