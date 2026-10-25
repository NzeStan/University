"""Analytics services: privacy-safe view recording and reports."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone

from university.analytics.conf import analytics_settings
from university.analytics.models import MetricDaily
from university.core.crypto import keyed_hash
from university.core.events import publish
from university.core.exceptions import NotFound, ValidationError
from university.core.ratelimit import rate_limit


def record_view(*, viewer: Any, content_type: str, object_id: Any, fingerprint: str) -> bool:
    """Count a view of any content the viewer may see — once per viewer per window, nobody stored."""
    from university.core.registry import registry

    adapter = registry.content_adapters.get(content_type)
    if adapter is None or not adapter.can_view(viewer, object_id):
        raise NotFound("Not found.")  # Unknown, hidden and nonexistent look the same.
    who = f"u:{viewer.pk}" if getattr(viewer, "is_authenticated", False) else f"a:{fingerprint}"
    rate_limit("analytics_view", key=who)
    token = keyed_hash(f"{content_type}:{object_id}:{who}", purpose="analytics.view")[:32]
    window = int(analytics_settings.get("VIEW_DEDUPE_HOURS", 24)) * 3600
    if not cache.add(f"analytics:view:{token}", 1, timeout=window):
        return False
    ref = adapter.resolve(object_id)
    payload: dict[str, Any] = {"content_type": content_type, "object_id": str(object_id)}
    if ref is not None and ref.scope:
        payload["scope_type"], payload["scope_id"] = ref.scope
    # No viewer id: trending and analytics need the fact, not the person.
    publish("content.viewed", payload)
    return True


def _range(start: dt.date | None, end: dt.date | None) -> tuple[dt.date, dt.date]:
    end = end or timezone.localdate()
    start = start or end - dt.timedelta(days=29)
    max_days = int(analytics_settings.get("MAX_RANGE_DAYS", 366))
    if start > end or (end - start).days + 1 > max_days:
        raise ValidationError(details={"from": [f"Choose up to {max_days} days, ending after the start."]})
    return start, end


def report(
    *,
    start: dt.date | None,
    end: dt.date | None,
    metrics: Iterable[str] = (),
    scope: tuple[str, str] | None = None,
) -> dict[str, Any]:
    start, end = _range(start, end)
    scope_type, scope_id = scope or ("", "")
    qs = MetricDaily.objects.filter(scope_type=scope_type, scope_id=scope_id, date__range=(start, end))
    wanted = [m for m in metrics if m]
    if wanted:
        qs = qs.filter(metric__in=wanted)
    names = wanted or sorted(set(qs.values_list("metric", flat=True)))
    threshold = int(analytics_settings.get("MIN_REPORTABLE", 5)) if scope else 0
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    series: dict[str, dict[dt.date, int]] = {m: {} for m in names}
    for row in qs.values("metric", "date", "count"):
        series.setdefault(row["metric"], {})[row["date"]] = row["count"]
    totals = dict(qs.values_list("metric").annotate(total=Sum("count")).values_list("metric", "total"))

    def shown(value: int) -> int | None:
        # Small numbers inside a scope can identify people: suppress them.
        return None if threshold and 0 < value < threshold else value

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "scope": {"type": scope_type, "id": scope_id} if scope else None,
        "suppression_threshold": threshold or None,
        "metrics": [
            {
                "metric": m,
                "total": shown(int(totals.get(m, 0))),
                "series": [{"date": d.isoformat(), "value": shown(series.get(m, {}).get(d, 0))} for d in days],
            }
            for m in names
        ],
    }


def known_metrics() -> list[str]:
    return sorted(set(MetricDaily.objects.values_list("metric", flat=True)))
