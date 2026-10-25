from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from university.institution.importer import import_institutions, parse
from university.institution.services import sync_institution_types


class Command(BaseCommand):
    help = "Import or update institutions (with domains and campuses) from a JSON or CSV file."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("path", help="Path to a .json or .csv file.")
        parser.add_argument(
            "--verify-domains",
            action="store_true",
            help="Mark imported email domains as verified (only for trusted sources).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"File not found: {path}")
        fmt = "csv" if path.suffix.lower() == ".csv" else "json"
        sync_institution_types()
        try:
            records = parse(path.read_text(encoding="utf-8"), fmt=fmt)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        result = import_institutions(records, verify_domains=options["verify_domains"])
        for error in result.errors:
            self.stderr.write(self.style.ERROR(error))
        if result.errors and not (result.created or result.updated):
            raise CommandError("Import failed; no changes were saved.")
        self.stdout.write(self.style.SUCCESS(f"Imported: {result.created} created, {result.updated} updated."))
