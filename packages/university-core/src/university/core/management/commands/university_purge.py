from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from university.core.registry import registry
from university.core.retention import run_retention


class Command(BaseCommand):
    help = "Apply data-retention policies contributed by installed University modules."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report counts without deleting.")
        parser.add_argument("--only", nargs="*", help="Run only the named policies.")
        parser.add_argument("--list", action="store_true", help="List policies and exit.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["list"]:
            for name, policy in sorted(registry.retention_policies.items()):
                self.stdout.write(f"{name:<40} {policy.setting:<40} {policy.description}")
            return
        results = run_retention(dry_run=options["dry_run"], only=options["only"])
        verb = "would purge" if options["dry_run"] else "purged"
        for name, count in results.items():
            if count < 0:
                self.stderr.write(self.style.ERROR(f"{name}: failed (see logs)"))
            else:
                self.stdout.write(f"{name}: {verb} {count}")
