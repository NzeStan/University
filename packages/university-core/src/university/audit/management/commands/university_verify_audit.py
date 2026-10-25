from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from university.audit.services import verify_entries


class Command(BaseCommand):
    help = "Verify the integrity of the audit log (per-entry HMACs and, if enabled, the hash chain)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--chain", action="store_true", help="Also verify the hash chain.")
        parser.add_argument("--limit", type=int, default=50, help="Maximum issues to print.")

    def handle(self, *args: Any, **options: Any) -> None:
        issues = 0
        for issue in verify_entries(check_chain=options["chain"] or None):
            issues += 1
            if issues <= options["limit"]:
                self.stderr.write(self.style.ERROR(f"{issue.entry_id}: {issue.problem}"))
        if issues:
            raise CommandError(f"Audit log verification failed: {issues} issue(s).")
        self.stdout.write(self.style.SUCCESS("Audit log verified: no issues found."))
