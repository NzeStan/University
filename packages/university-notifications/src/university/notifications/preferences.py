"""Categories, effective per-channel preferences and quiet hours.

Preferences live in Core's ``NotificationSettings`` (``me/notifications/``):
master switches per channel, ``{category: {channel: bool}}`` overrides, quiet
hours and the digest frequency. This module combines them with the category
defaults configured in ``NOTIFICATIONS.CATEGORIES``.
"""

from __future__ import annotations

import datetime as dt
import zoneinfo
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.utils import timezone

from university.notifications.conf import notification_settings
from university.notifications.constants import EMAIL_IMMEDIATE, Channel

CHANNEL_KEYS = tuple(c.value for c in Channel)


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    #: ``{channel: False | True | "immediate" | "digest"}``
    defaults: dict[str, Any]
    mandatory: bool = False
    bypass_quiet_hours: bool = False


def categories() -> list[Category]:
    out = []
    for key, conf in (notification_settings.get("CATEGORIES") or {}).items():
        if not conf:
            continue
        out.append(
            Category(
                key=key,
                label=str(conf.get("label", key)),
                defaults={ch: conf.get(ch, ch == Channel.IN_APP) for ch in CHANNEL_KEYS},
                mandatory=bool(conf.get("mandatory", False)),
                bypass_quiet_hours=bool(conf.get("bypass_quiet_hours", False)),
            )
        )
    return out


def get_category(key: str) -> Category:
    for category in categories():
        if category.key == key:
            return category
    # Unknown categories (e.g. a verb registered without configuration) are in-app only.
    return Category(key=key, label=key, defaults={Channel.IN_APP: True})


def channel_mode(prefs: Any, category: Category, channel: str) -> Any:
    """The effective mode of ``channel`` for ``category``: False, True, "immediate" or "digest"."""
    if channel == Channel.IN_APP and category.mandatory:
        return True
    if not getattr(prefs, f"{channel}_enabled", True):
        return False
    default = category.defaults.get(channel, False)
    override = ((prefs.categories or {}).get(category.key) or {}).get(channel)
    if override is None:
        return default
    if not override:
        return False
    # Opting in to a channel that is off by default.
    return default or (EMAIL_IMMEDIATE if channel == Channel.EMAIL else True)


def user_zone(user: Any) -> dt.tzinfo:
    name = getattr(user, "timezone", "") or settings.TIME_ZONE
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return dt.UTC


def in_quiet_hours(user: Any, prefs: Any, now: dt.datetime | None = None) -> bool:
    start, end = prefs.quiet_hours_start, prefs.quiet_hours_end
    if start is None or end is None or start == end:
        return False
    local = (now or timezone.now()).astimezone(user_zone(user)).time()
    if start < end:
        return start <= local < end
    return local >= start or local < end  # The window wraps past midnight.
