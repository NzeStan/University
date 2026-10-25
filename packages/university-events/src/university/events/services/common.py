from __future__ import annotations

import datetime as dt
import zoneinfo
from collections.abc import Mapping
from typing import Any

from django.utils import timezone

from university.core.exceptions import ValidationError
from university.core.providers import get_spam_filter
from university.core.providers.spam import SpamAction


def screen(text: str, *, actor: Any) -> None:
    """Reject spam outright; events are drafts until published, so 'review' passes."""
    if not text.strip():
        return
    verdict = get_spam_filter().check(text, actor=actor, context={"kind": "event"})
    if verdict.action == SpamAction.REJECT:
        raise ValidationError(
            "This content was rejected by our spam filter.",
            code="content_rejected",
            details={"reasons": list(verdict.reasons)},
        )


def valid_timezone(name: str) -> str:
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        raise ValidationError(details={"timezone": ["Unknown time zone."]}) from None
    return name


def check_window(
    starts_at: dt.datetime, ends_at: dt.datetime, *, field: str = "ends_at", max_days: int | None = None
) -> None:
    if ends_at <= starts_at:
        raise ValidationError(details={field: ["Must be after the start."]})
    if max_days is not None and ends_at - starts_at > dt.timedelta(days=max_days):
        raise ValidationError(details={field: [f"Can't last longer than {max_days} days."]})


def in_future(value: dt.datetime, field: str) -> None:
    if value <= timezone.now():
        raise ValidationError(details={field: ["Must be in the future."]})


def https_url(value: str, field: str) -> str:
    value = (value or "").strip()
    if value and not value.lower().startswith("https://"):
        raise ValidationError(details={field: ["Use an https:// link."]})
    return value


def clean_speakers(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 20:
        raise ValidationError(details={"speakers": ["Provide up to 20 speakers."]})
    out = []
    for item in value:
        if not isinstance(item, Mapping) or not str(item.get("name", "")).strip():
            raise ValidationError(details={"speakers": ["Each speaker needs a name."]})
        out.append({"name": str(item["name"]).strip()[:100], "title": str(item.get("title", "")).strip()[:100]})
    return out
