"""Creator profiles, categories and media kits."""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Mapping
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Sum

from university.audit.services import record as audit
from university.core.events import publish
from university.core.exceptions import Conflict, ValidationError
from university.core.providers import get_spam_filter
from university.core.providers.spam import SpamAction
from university.creator import events
from university.creator.conf import creator_settings
from university.creator.constants import (
    TRUSTED_COUNT_SOURCES,
    OwnershipStatus,
    ProfileStatus,
)
from university.creator.models import CreatorCategory, CreatorProfile, LinkedAccount, MediaKit
from university.creator.selectors import own_profile

PROFILE_FIELDS = (
    "headline",
    "bio",
    "city",
    "country",
    "languages",
    "is_discoverable",
    "open_to_sponsorships",
    "business_email",
)


def screen(text: str, *, actor: Any, kind: str) -> None:
    if not text.strip():
        return
    verdict = get_spam_filter().check(text, actor=actor, context={"kind": kind})
    if verdict.action == SpamAction.REJECT:
        raise ValidationError(
            "This content was rejected by our spam filter.",
            code="content_rejected",
            details={"reasons": list(verdict.reasons)},
        )


def sync_categories() -> None:
    """Seed configured categories (existing rows keep admin edits)."""
    for position, (key, name) in enumerate((creator_settings.get("CATEGORIES") or {}).items()):
        CreatorCategory.objects.get_or_create(key=key, defaults={"name": name, "position": position})


def resolve_categories(keys: Iterable[str]) -> list[CreatorCategory]:
    keys = list(dict.fromkeys(keys))
    limit = int(creator_settings.get("MAX_CATEGORIES_PER_PROFILE", 3))
    if len(keys) > limit:
        raise ValidationError(details={"categories": [f"Choose up to {limit} categories."]})
    found = list(CreatorCategory.objects.filter(key__in=keys, is_active=True))
    if len(found) != len(keys):
        raise ValidationError(details={"categories": ["Unknown category."]})
    return found


def _clean_languages(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 10:
        raise ValidationError(details={"languages": ["Up to 10 language codes."]})
    return [str(v).strip()[:10] for v in value if str(v).strip()]


def _apply(profile: CreatorProfile, data: Mapping[str, Any]) -> list[str]:
    changed = []
    for key in PROFILE_FIELDS:
        if key in data:
            value = data[key]
            if key == "languages":
                value = _clean_languages(value)
            elif key == "country":
                value = (value or "").upper()
            setattr(profile, key, value)
            changed.append(key)
    return changed


@transaction.atomic
def create_profile(*, user: Any, data: Mapping[str, Any], categories: Iterable[str] = ()) -> CreatorProfile:
    if CreatorProfile.objects.filter(user=user).exists():
        raise Conflict("You already have a creator profile.", code="profile_exists")
    profile = CreatorProfile(user=user)
    _apply(profile, data)
    screen(f"{profile.headline}\n{profile.bio}", actor=user, kind="creator_profile")
    cats = resolve_categories(categories)
    try:
        with transaction.atomic():
            profile.save()
    except IntegrityError:
        raise Conflict("You already have a creator profile.", code="profile_exists") from None
    profile.categories.set(cats)
    audit("creator.profile.created", actor=user, target=profile, category="creator")
    publish(events.PROFILE_CREATED, {"profile_id": profile.pk, "user_id": user.pk}, actor=user)
    return profile


@transaction.atomic
def update_profile(*, user: Any, data: Mapping[str, Any], categories: Iterable[str] | None = None) -> CreatorProfile:
    profile = own_profile(user)
    changed = _apply(profile, data)
    if "status" in data:
        if data["status"] not in ProfileStatus.values:
            raise ValidationError(details={"status": ["Unknown status."]})
        profile.status = data["status"]
        changed.append("status")
    screen(f"{profile.headline}\n{profile.bio}", actor=user, kind="creator_profile")
    profile.save()
    if categories is not None:
        profile.categories.set(resolve_categories(categories))
        changed.append("categories")
    publish(events.PROFILE_UPDATED, {"profile_id": profile.pk, "fields": changed}, actor=user)
    return profile


def recalculate_reach(profile: CreatorProfile) -> int:
    reach = (
        LinkedAccount.objects.filter(
            profile=profile, ownership=OwnershipStatus.VERIFIED, count_source__in=TRUSTED_COUNT_SOURCES
        ).aggregate(total=Sum("follower_count"))["total"]
        or 0
    )
    CreatorProfile.objects.filter(pk=profile.pk).update(verified_reach=reach)
    profile.verified_reach = reach
    return reach


# --------------------------------------------------------------- media kit
def _new_token() -> str:
    return secrets.token_urlsafe(24)


def get_media_kit(profile: CreatorProfile) -> MediaKit:
    kit = MediaKit.objects.filter(profile=profile).first()
    if kit is None:
        try:
            with transaction.atomic():
                kit = MediaKit.objects.create(profile=profile, share_token=_new_token())
        except IntegrityError:
            kit = MediaKit.objects.get(profile=profile)
    return kit


def _clean_percentages(value: Any, field: str) -> dict[str, dict[str, float]]:
    if not isinstance(value, Mapping) or len(value) > 6:
        raise ValidationError(details={field: ["Give up to 6 breakdowns."]})
    clean: dict[str, dict[str, float]] = {}
    for group, shares in value.items():
        if not isinstance(shares, Mapping) or len(shares) > 30:
            raise ValidationError(details={field: ["Each breakdown maps labels to percentages."]})
        try:
            parsed = {str(k)[:40]: round(float(v), 2) for k, v in shares.items()}
        except (TypeError, ValueError):
            raise ValidationError(details={field: ["Percentages must be numbers."]}) from None
        if any(v < 0 for v in parsed.values()) or sum(parsed.values()) > 100.5:
            raise ValidationError(
                details={field: [f"'{group}' percentages must be positive and add up to 100 or less."]}
            )
        clean[str(group)[:40]] = parsed
    return clean


def _clean_rates(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 30:
        raise ValidationError(details={"rates": ["Give up to 30 rates."]})
    currencies = creator_settings.get("CURRENCIES", [])
    clean = []
    for item in value:
        try:
            price = int(item.get("price_minor"))
        except (AttributeError, TypeError, ValueError):
            raise ValidationError(details={"rates": ["Each rate needs a whole price_minor."]}) from None
        deliverable = str(item.get("deliverable", "")).strip()[:100]
        currency = str(item.get("currency") or creator_settings.get("DEFAULT_CURRENCY")).upper()
        if not deliverable or price < 0 or currency not in currencies:
            raise ValidationError(
                details={"rates": ["Each rate needs a deliverable, a price and a supported currency."]}
            )
        clean.append(
            {
                "deliverable": deliverable,
                "price_minor": price,
                "currency": currency,
                "notes": str(item.get("notes", ""))[:300],
            }
        )
    return clean


def _clean_highlights(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 30:
        raise ValidationError(details={"highlights": ["Give up to 30 highlights."]})
    clean = []
    for item in value:
        if not isinstance(item, Mapping) or not str(item.get("title", "")).strip():
            raise ValidationError(details={"highlights": ["Each highlight needs a title."]})
        url = str(item.get("url", "")).strip()[:300]
        if url and not url.lower().startswith("https://"):
            raise ValidationError(details={"highlights": ["Links must use https://."]})
        clean.append(
            {
                "title": str(item["title"]).strip()[:150],
                "brand": str(item.get("brand", ""))[:100],
                "url": url,
                "year": str(item.get("year", ""))[:4],
            }
        )
    return clean


@transaction.atomic
def update_media_kit(*, user: Any, data: Mapping[str, Any]) -> MediaKit:
    profile = own_profile(user)
    kit = get_media_kit(profile)
    if "visibility" in data:
        kit.visibility = data["visibility"]
    if "summary" in data:
        kit.summary = str(data["summary"])[:5000]
    if "audience" in data:
        kit.audience = _clean_percentages(data["audience"], "audience")
    if "rates" in data:
        kit.rates = _clean_rates(data["rates"])
    if "highlights" in data:
        kit.highlights = _clean_highlights(data["highlights"])
    if "show_platform_stats" in data:
        kit.show_platform_stats = bool(data["show_platform_stats"])
    screen(kit.summary, actor=user, kind="media_kit")
    kit.save()
    return kit


@transaction.atomic
def rotate_share_token(*, user: Any) -> MediaKit:
    kit = get_media_kit(own_profile(user))
    kit.share_token = _new_token()
    kit.save(update_fields=["share_token", "updated_at"])
    return kit
