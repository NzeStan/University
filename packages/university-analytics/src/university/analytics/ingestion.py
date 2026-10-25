"""Turn platform events into daily counters (and minimised sink events)."""

from __future__ import annotations

import datetime as dt
import fnmatch
import logging
from typing import Any

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from university.analytics.conf import analytics_settings
from university.analytics.models import MetricDaily
from university.core.crypto import keyed_hash
from university.core.events import Event

logger = logging.getLogger("university.analytics")


def increment(
    metric: str, *, day: dt.date | None = None, scope: tuple[str, str] | None = None, amount: int = 1
) -> None:
    day = day or timezone.localdate()
    scope_type, scope_id = scope or ("", "")
    keys = {"date": day, "metric": metric[:100], "scope_type": scope_type[:32], "scope_id": str(scope_id)[:64]}
    if MetricDaily.objects.filter(**keys).update(count=F("count") + amount):
        return
    try:
        with transaction.atomic():
            MetricDaily.objects.create(count=amount, **keys)
    except IntegrityError:  # Created concurrently.
        MetricDaily.objects.filter(**keys).update(count=F("count") + amount)


def tracked(name: str) -> bool:
    if any(fnmatch.fnmatchcase(name, p) for p in analytics_settings.get("EXCLUDE") or []):
        return False
    return any(fnmatch.fnmatchcase(name, p) for p in analytics_settings.get("TRACK") or [])


def dimensions(payload: dict[str, Any]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for key, scope_type in (analytics_settings.get("DIMENSIONS") or {}).items():
        if payload.get(key):
            found.append((scope_type, str(payload[key])))
    if payload.get("scope_type") and payload.get("scope_id"):
        found.append((str(payload["scope_type"]), str(payload["scope_id"])))
    return list(dict.fromkeys(found))


def metric_name(event: Event) -> str:
    if event.name == "content.viewed":
        return f"views.{event.payload.get('content_type', 'unknown')}"
    return event.name


def _period_starts(day: dt.date) -> dict[str, dt.date]:
    return {"daily": day, "weekly": day - dt.timedelta(days=day.weekday()), "monthly": day.replace(day=1)}


def count_active(actor_id: str, day: dt.date) -> None:
    for period, start in _period_starts(day).items():
        token = keyed_hash(f"{actor_id}:{period}:{start.isoformat()}", purpose="analytics.active")[:32]
        ttl = {"daily": 2, "weekly": 8, "monthly": 32}[period] * 86400
        if cache.add(f"analytics:active:{token}", 1, timeout=ttl):
            increment(f"active_users.{period}", day=start)


def handle_event(event: Event) -> None:
    if not tracked(event.name):
        return
    day = timezone.localdate()
    payload = dict(event.payload)
    metric = metric_name(event)
    increment(metric, day=day)
    scopes = dimensions(payload)
    for scope in scopes:
        increment(metric, day=day, scope=scope)
    if event.actor_id and analytics_settings.get("ACTIVE_USERS", True):
        count_active(event.actor_id, day)
    _emit(event, metric, scopes)


def _emit(event: Event, metric: str, scopes: list[tuple[str, str]]) -> None:
    from university.analytics.sinks import get_sinks

    sinks = get_sinks()
    if not sinks:
        return
    month = timezone.now().strftime("%Y-%m")
    record = {
        "event": metric,
        "occurred_at": timezone.now().replace(second=0, microsecond=0).isoformat(),
        "dimensions": [f"{t}:{i}" for t, i in scopes],
        # Pseudonymous, and different every month: counts uniques without tracking people.
        "actor": keyed_hash(f"{event.actor_id}:{month}", purpose="analytics.sink")[:24] if event.actor_id else None,
    }
    for sink in sinks:
        try:
            sink.emit(record)
        except Exception:
            logger.exception("Analytics sink %r failed", sink)
