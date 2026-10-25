"""Remind attendees of upcoming events. Schedule hourly (cron, Celery beat)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from university.events.services import send_reminders


class Command(BaseCommand):
    help = "Send reminders for events starting within EVENTS.REMINDER_HOURS."

    def handle(self, *args: Any, **options: Any) -> None:
        sent = send_reminders()
        self.stdout.write(self.style.SUCCESS(f"Sent {sent} reminder(s)."))
