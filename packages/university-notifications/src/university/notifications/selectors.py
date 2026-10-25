from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from university.notifications.models import Notification, PushDevice


def feed(user: Any, *, unread: bool | None = None, category: str | None = None) -> QuerySet[Notification]:
    qs = Notification.objects.filter(recipient=user, in_app=True).select_related("actor")
    if unread is True:
        qs = qs.filter(read_at__isnull=True)
    elif unread is False:
        qs = qs.filter(read_at__isnull=False)
    if category:
        qs = qs.filter(category=category)
    return qs


#: Counts above this are reported as the cap (badges show "99+" anyway).
COUNT_CAP = 1000


def _capped(qs: QuerySet[Notification]) -> int:
    return len(qs.values_list("pk", flat=True)[:COUNT_CAP])


def counts(user: Any) -> dict[str, int]:
    base = Notification.objects.filter(recipient=user, in_app=True)
    return {
        "unread": _capped(base.filter(read_at__isnull=True)),
        "unseen": _capped(base.filter(seen_at__isnull=True)),
    }


def devices(user: Any) -> QuerySet[PushDevice]:
    return PushDevice.objects.filter(user=user).order_by("-last_seen_at")
