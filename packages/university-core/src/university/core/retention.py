"""Data-retention helpers and Core's own retention policies.

Modules contribute :class:`~university.core.declarations.RetentionPolicy`
objects through ``UniversityAppConfig.get_retention_policies()``. Run them
with ``manage.py university_purge`` (or schedule the ``university.core.purge``
task with Celery beat / cron). Every value is configurable through
``UNIVERSITY["RETENTION"]``; ``None`` disables a policy.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable

from django.db.models import QuerySet
from django.utils import timezone

from university.core.conf import university_settings
from university.core.declarations import RetentionPolicy
from university.core.registry import registry
from university.core.tasks import task

logger = logging.getLogger("university.retention")


def cutoff_days(setting: str) -> Callable[[], dt.datetime | None]:
    def cutoff() -> dt.datetime | None:
        days = university_settings.get(f"RETENTION.{setting}", None)
        return None if days is None else timezone.now() - dt.timedelta(days=int(days))

    return cutoff


def cutoff_hours(setting: str) -> Callable[[], dt.datetime | None]:
    def cutoff() -> dt.datetime | None:
        hours = university_settings.get(f"RETENTION.{setting}", None)
        return None if hours is None else timezone.now() - dt.timedelta(hours=int(hours))

    return cutoff


def delete_queryset(queryset: QuerySet, dry_run: bool) -> int:
    if dry_run:
        return queryset.count()
    deleted, _ = queryset.delete()
    return deleted


def run_retention(*, dry_run: bool = False, only: list[str] | None = None) -> dict[str, int]:
    results: dict[str, int] = {}
    for name, policy in sorted(registry.retention_policies.items()):
        if only and name not in only:
            continue
        cutoff = policy.cutoff()
        if cutoff is None:
            continue
        try:
            results[name] = policy.purge(cutoff, dry_run)
        except Exception:
            logger.exception("Retention policy %s failed", name)
            results[name] = -1
    return results


@task(name="university.core.purge")
def purge_task() -> None:
    results = run_retention()
    logger.info("Retention run completed", extra={"retention_results": results})


def core_retention_policies() -> list[RetentionPolicy]:
    from university.core.models import IdempotencyRecord, WebhookEvent

    return [
        RetentionPolicy(
            name="core.idempotency_records",
            description="Stored idempotent responses.",
            setting="RETENTION.IDEMPOTENCY_RECORD_HOURS",
            cutoff=cutoff_hours("IDEMPOTENCY_RECORD_HOURS"),
            purge=lambda cutoff, dry: delete_queryset(IdempotencyRecord.objects.filter(created_at__lt=cutoff), dry),
        ),
        RetentionPolicy(
            name="core.webhook_events",
            description="Inbound webhook delivery log.",
            setting="RETENTION.WEBHOOK_EVENT_DAYS",
            cutoff=cutoff_days("WEBHOOK_EVENT_DAYS"),
            purge=lambda cutoff, dry: delete_queryset(WebhookEvent.objects.filter(created_at__lt=cutoff), dry),
        ),
    ]
