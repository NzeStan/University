"""Publish scheduled episodes that are due. Schedule every minute or few (cron, Celery beat)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from university.podcast.services import publish_due_episodes


class Command(BaseCommand):
    help = "Publish scheduled podcast episodes whose time has come."

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write(self.style.SUCCESS(f"Published {publish_due_episodes()} episode(s)."))
