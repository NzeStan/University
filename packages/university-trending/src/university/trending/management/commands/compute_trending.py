"""Recompute trending scores. Schedule every few minutes (cron, Celery beat)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from university.trending.services import compute_trending


class Command(BaseCommand):
    help = "Recompute trending scores from recent engagement signals."

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write(self.style.SUCCESS(f"Scored {compute_trending()} item(s)."))
