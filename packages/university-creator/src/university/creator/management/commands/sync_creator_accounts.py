"""Refresh follower counts of verified linked accounts. Schedule hourly (cron, Celery beat)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from university.creator.services import sync_linked_accounts


class Command(BaseCommand):
    help = "Refresh verified linked accounts that are due (CREATOR.SYNC_INTERVAL_HOURS)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args: Any, limit: int, **options: Any) -> None:
        synced = sync_linked_accounts(limit)
        self.stdout.write(self.style.SUCCESS(f"Synced {synced} account(s)."))
