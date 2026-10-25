"""Trending: signal ingestion, score computation and permission-aware reads."""

from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Case, F, IntegerField, Sum, When
from django.utils import timezone

from university.core.crypto import keyed_hash
from university.core.events import Event
from university.core.tasks import task
from university.trending.algorithms import ItemStats, get_algorithm
from university.trending.conf import trending_settings
from university.trending.models import ACTORS_SIGNAL, TrendingScore, TrendingSignal

logger = logging.getLogger("university.trending")


def _hour(now: dt.datetime | None = None) -> dt.datetime:
    return (now or timezone.now()).replace(minute=0, second=0, microsecond=0)


def _bump(content_type: str, object_id: str, signal: str) -> None:
    keys = {"content_type": content_type[:64], "object_id": object_id[:64], "signal": signal[:32], "hour": _hour()}
    if TrendingSignal.objects.filter(**keys).update(count=F("count") + 1):
        return
    try:
        with transaction.atomic():
            TrendingSignal.objects.create(count=1, **keys)
    except IntegrityError:
        TrendingSignal.objects.filter(**keys).update(count=F("count") + 1)


def _first_time(*parts: str) -> bool:
    token = keyed_hash(":".join(parts), purpose="trending.dedupe")[:32]
    return bool(cache.add(f"trending:{token}", 1, timeout=int(trending_settings.get("DEDUPE_HOURS", 24)) * 3600))


def record(event: Event) -> None:
    rule = (trending_settings.get("SIGNALS") or {}).get(event.name)
    if not rule:
        return
    payload = event.payload
    content_type = rule.get("content_type") or payload.get(rule.get("content_type_key", ""), "")
    object_id = str(payload.get(rule["id_key"]) or "")
    signal = rule["signal"]
    if not content_type or not object_id:
        return
    actor = event.actor_id
    if actor:
        # One person can't pump an item: each signal counts once per person per window …
        if not _first_time(content_type, object_id, signal, actor):
            return
        # … and distinct people are tracked for the breadth requirement.
        if _first_time(content_type, object_id, "actor", actor):
            _bump(content_type, object_id, ACTORS_SIGNAL)
    elif signal == "view":
        # Views carry no actor (privacy); the analytics module already de-duplicates them.
        pass
    _bump(content_type, object_id, signal)


def handle_event(event: Event) -> None:
    record(event)


# -------------------------------------------------------------- computation
@task(name="university.trending.compute_trending")
def compute_trending() -> int:
    from university.core.registry import registry

    now = timezone.now()
    window = int(trending_settings.get("WINDOW_HOURS", 48))
    recent_hours = int(trending_settings.get("VELOCITY_HOURS", 6))
    window_start = _hour(now - dt.timedelta(hours=window))
    recent_start = _hour(now - dt.timedelta(hours=recent_hours))
    rows = (
        TrendingSignal.objects.filter(hour__gte=window_start)
        .values("content_type", "object_id", "signal")
        .annotate(
            total=Sum("count"),
            recent=Sum(Case(When(hour__gte=recent_start, then=F("count")), default=0, output_field=IntegerField())),
        )
    )
    stats: dict[tuple[str, str], ItemStats] = defaultdict(ItemStats)
    for row in rows:
        item = stats[(row["content_type"], row["object_id"])]
        if row["signal"] == ACTORS_SIGNAL:
            item.unique_actors = int(row["total"] or 0)
        else:
            item.window[row["signal"]] = int(row["total"] or 0)
            item.recent[row["signal"]] = int(row["recent"] or 0)
    algorithm = get_algorithm()
    scored: dict[str, list[TrendingScore]] = defaultdict(list)
    for (content_type, object_id), item in stats.items():
        adapter = registry.content_adapters.get(content_type)
        ref = adapter.resolve(object_id) if adapter else None
        if ref is None:
            continue
        created = ref.created_at or window_start
        item.age_hours = max((now - created).total_seconds() / 3600, 0.0)
        score = algorithm.score(item)
        if score <= 0:
            continue
        scope_type, scope_id = ref.scope or ("", "")
        scored[content_type].append(
            TrendingScore(
                content_type=content_type,
                object_id=object_id,
                scope_type=scope_type,
                scope_id=str(scope_id),
                author_id="" if ref.is_anonymous else str(ref.author_id or ""),
                score=score,
                computed_at=now,
            )
        )
    limit = int(trending_settings.get("MAX_ITEMS_PER_TYPE", 500))
    keep = [s for items in scored.values() for s in sorted(items, key=lambda s: -s.score)[:limit]]
    with transaction.atomic():
        TrendingScore.objects.all().delete()
        TrendingScore.objects.bulk_create(keep)
    return len(keep)


# --------------------------------------------------------------------- reads
def trending(
    *, viewer: Any, content_type: str | None = None, scope: tuple[str, str] | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """Top items the viewer may see, with author diversity."""
    from university.core.registry import registry

    qs = TrendingScore.objects.order_by("-score", "id")
    if content_type:
        qs = qs.filter(content_type=content_type)
    if scope:
        qs = qs.filter(scope_type=scope[0], scope_id=str(scope[1]))
    max_per_author = int(trending_settings.get("MAX_PER_AUTHOR", 2))
    per_author: dict[str, int] = defaultdict(int)
    out: list[dict[str, Any]] = []
    for row in qs.iterator(chunk_size=200):
        adapter = registry.content_adapters.get(row.content_type)
        if adapter is None:
            continue
        try:
            if not adapter.can_view(viewer, row.object_id):
                continue  # Private, hidden, blocked or deleted for this viewer.
        except Exception:
            logger.exception("Visibility check failed; skipping the item.", extra={"content_type": row.content_type})
            continue  # Fail closed.
        if row.author_id and max_per_author:
            if per_author[row.author_id] >= max_per_author:
                continue
            per_author[row.author_id] += 1
        ref = adapter.resolve(row.object_id)
        title = (ref.excerpt.strip().splitlines() or [""])[0][:160] if ref else ""
        out.append(
            {"content_type": row.content_type, "object_id": row.object_id, "score": round(row.score, 6), "title": title}
        )
        if len(out) >= limit:
            break
    return out


def scores_for(content_type: str, object_ids: Iterable[str]) -> dict[str, float]:
    """Core hook ``content.trending_scores``: scores for feeds that rank by them."""
    ids = [str(i) for i in object_ids]
    if not ids:
        return {}
    return dict(
        TrendingScore.objects.filter(content_type=content_type, object_id__in=ids).values_list("object_id", "score")
    )
