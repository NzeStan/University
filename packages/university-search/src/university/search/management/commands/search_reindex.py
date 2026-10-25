"""(Re)build the search index from live content. Run after installing or changing SOURCES."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from university.search.indexing import reindex


class Command(BaseCommand):
    help = "Index every live item of the configured (or given) content types."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--type", action="append", dest="types", help="Content type (repeatable).")

    def handle(self, *args: Any, types: list[str] | None = None, **options: Any) -> None:
        self.stdout.write(self.style.SUCCESS(f"Indexed {reindex(types)} item(s)."))
