"""Expire abandoned checkouts and retry pending refunds. Schedule every few minutes."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from university.payments.services import expire_intents, retry_refunds


class Command(BaseCommand):
    help = "Expire abandoned checkouts and resubmit refunds that never reached the provider."

    def handle(self, *args: Any, **options: Any) -> None:
        expired = expire_intents()
        retried = retry_refunds()
        self.stdout.write(self.style.SUCCESS(f"Expired {expired} checkout(s); retried {retried} refund(s)."))
