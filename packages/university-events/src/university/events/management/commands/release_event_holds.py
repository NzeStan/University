"""Expire unpaid ticket holds. Schedule every few minutes when paid tickets are on."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from university.events.services import release_expired_holds


class Command(BaseCommand):
    help = "Expire unpaid ticket holds and pass the seats to the waitlist."

    def handle(self, *args: Any, **options: Any) -> None:
        released = release_expired_holds()
        self.stdout.write(self.style.SUCCESS(f"Released {released} hold(s)."))
