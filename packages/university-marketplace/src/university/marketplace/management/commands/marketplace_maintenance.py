"""Expire unpaid orders and auto-complete delivered ones. Schedule every few minutes."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from university.marketplace.services import auto_complete_orders, expire_unpaid_orders


class Command(BaseCommand):
    help = "Release stock from unpaid orders and complete fulfilled orders past their dispute window."

    def handle(self, *args: Any, **options: Any) -> None:
        expired = expire_unpaid_orders()
        completed = auto_complete_orders()
        self.stdout.write(self.style.SUCCESS(f"Expired {expired} order(s); auto-completed {completed}."))
