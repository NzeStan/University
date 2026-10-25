"""Send email digests. Schedule daily and weekly runs (cron, Celery beat)::

python manage.py send_notification_digests --frequency daily
python manage.py send_notification_digests --frequency weekly
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from university.notifications.delivery import send_digests


class Command(BaseCommand):
    help = "Email queued notifications to people whose digest frequency matches."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--frequency", choices=["daily", "weekly"], required=True)

    def handle(self, *args: Any, frequency: str, **options: Any) -> None:
        sent = send_digests(frequency)
        self.stdout.write(self.style.SUCCESS(f"Sent {sent} {frequency} digest(s)."))
