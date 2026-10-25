"""Privacy-conscious creator analytics: per-day counters, never per-viewer records.

Counters are fed by ids-only platform events (follows, reactions, comments …)
and by views of creator pages and media kits. Repeat views are deduplicated
with a short-lived keyed hash in the cache, never stored in the database.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.utils import timezone

from university.core.crypto import keyed_hash
from university.core.exceptions import ValidationError
from university.creator.conf import creator_settings
from university.creator.constants import Metric
from university.creator.models import CreatorDailyStat, CreatorProfile, LinkedAccountSnapshot


def profile_id_for_user(user_id: Any) -> Any:
    if not user_id:
        return None
    return CreatorProfile.objects.filter(user_id=user_id).values_list("pk", flat=True).first()


def increment(profile_id: Any, metric: str, amount: int = 1, *, day: dt.date | None = None) -> None:
    day = day or timezone.localdate()
    updated = CreatorDailyStat.objects.filter(profile_id=profile_id, date=day, metric=metric).update(
        value=F("value") + amount
    )
    if updated:
        return
    try:
        with transaction.atomic():
            CreatorDailyStat.objects.create(profile_id=profile_id, date=day, metric=metric, value=amount)
    except IntegrityError:  # Created concurrently.
        CreatorDailyStat.objects.filter(profile_id=profile_id, date=day, metric=metric).update(
            value=F("value") + amount
        )


def record_view(profile: CreatorProfile, viewer: Any, metric: str, *, fingerprint: str = "") -> bool:
    """Count a view unless it's the creator or a repeat within the dedupe window."""
    if getattr(viewer, "is_authenticated", False):
        if viewer.pk == profile.user_id:
            return False
        who = f"u:{viewer.pk}"
    else:
        who = f"a:{fingerprint}"
    key = "creator:view:" + keyed_hash(f"{profile.pk}:{metric}:{who}", purpose="creator.view_dedupe")[:32]
    hours = int(creator_settings.get("VIEW_DEDUPE_HOURS", 24))
    if not cache.add(key, 1, timeout=hours * 3600):
        return False
    increment(profile.pk, metric)
    return True


def _range(start: dt.date | None, end: dt.date | None) -> tuple[dt.date, dt.date]:
    end = end or timezone.localdate()
    start = start or end - dt.timedelta(days=29)
    if start > end:
        raise ValidationError(details={"from": ["Must be on or before 'to'."]})
    max_days = int(creator_settings.get("ANALYTICS_MAX_RANGE_DAYS", 366))
    if (end - start).days + 1 > max_days:
        raise ValidationError(details={"from": [f"Choose at most {max_days} days."]})
    return start, end


def report(
    profile: CreatorProfile, *, start: dt.date | None = None, end: dt.date | None = None, metrics: Iterable[str] = ()
) -> dict[str, Any]:
    start, end = _range(start, end)
    wanted = [m for m in metrics if m in Metric.values] or list(Metric.values)
    rows = CreatorDailyStat.objects.filter(profile=profile, date__range=(start, end), metric__in=wanted)
    series: dict[str, dict[str, int]] = {m: {} for m in wanted}
    for row in rows.values("metric", "date", "value"):
        series[row["metric"]][row["date"].isoformat()] = row["value"]
    totals = dict(rows.values_list("metric").annotate(total=Sum("value")).values_list("metric", "total"))
    days = [(start + dt.timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    accounts = []
    for account in profile.linked_accounts.all():
        points = dict(
            LinkedAccountSnapshot.objects.filter(account=account, date__range=(start, end)).values_list(
                "date", "follower_count"
            )
        )
        accounts.append(
            {
                "id": account.pk,
                "provider": account.provider,
                "handle": account.handle,
                "series": [{"date": d.isoformat(), "followers": points[d]} for d in sorted(points)],
            }
        )
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "metrics": [
            {
                "metric": m,
                "total": int(totals.get(m, 0)),
                "series": [{"date": d, "value": series[m].get(d, 0)} for d in days],
            }
            for m in wanted
        ],
        "net_followers": int(totals.get(Metric.FOLLOWERS_GAINED, 0)) - int(totals.get(Metric.FOLLOWERS_LOST, 0)),
        "linked_accounts": accounts,
    }
