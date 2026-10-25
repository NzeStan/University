"""Bulk import of institution reference data.

Institution data is configuration, not code: deployments import their own
lists (national registries, regulator exports …). Records are upserted by
``slug``, so imports are idempotent and safe to re-run.

JSON format (a list of objects)::

    [{
        "name": "Example University", "short_name": "EXU", "slug": "exu",
        "type": "university", "ownership": "public", "country": "NG",
        "region": "Lagos", "city": "Lagos", "website": "https://exu.example",
        "domains": ["exu.example", {"domain": "students.exu.example"}],
        "campuses": [{"name": "Main Campus", "slug": "main", "is_main": true}]
    }]

CSV files use the flat columns ``name, short_name, slug, type, ownership,
country, region, city, website, domains`` (domains separated by ``;``).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction
from django.utils.text import slugify

from university.institution.models import Campus, Institution, InstitutionDomain, InstitutionType

FIELDS = ("name", "short_name", "type", "ownership", "country", "region", "city", "website", "description")


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)


def parse(content: str, *, fmt: str) -> list[dict[str, Any]]:
    if fmt == "json":
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError("The JSON document must be a list of institutions.")
        return data
    rows = list(csv.DictReader(io.StringIO(content)))
    for row in rows:
        row["domains"] = [d.strip() for d in (row.get("domains") or "").split(";") if d.strip()]
    return rows


@transaction.atomic
def import_institutions(records: list[dict[str, Any]], *, verify_domains: bool = False) -> ImportResult:
    result = ImportResult()
    types = {t.key: t for t in InstitutionType.objects.all()}
    for index, record in enumerate(records, start=1):
        name = str(record.get("name") or "").strip()
        type_key = str(record.get("type") or "other").strip()
        if not name or type_key not in types:
            result.errors.append(f"record {index}: missing name or unknown type {type_key!r}")
            continue
        slug = str(record.get("slug") or slugify(record.get("short_name") or name))[:100]
        values = {f: record[f] for f in FIELDS if f in record and f != "type"}
        values["type"] = types[type_key]
        values["country"] = str(values.get("country", "")).upper()[:2]
        institution, created = Institution.all_objects.update_or_create(slug=slug, defaults=values)
        try:
            institution.full_clean(validate_unique=False, validate_constraints=False)
        except Exception as exc:
            result.errors.append(f"record {index} ({slug}): {exc}")
            transaction.set_rollback(True)
            return result
        result.created += int(created)
        result.updated += int(not created)
        for entry in record.get("domains") or []:
            spec = entry if isinstance(entry, dict) else {"domain": entry}
            InstitutionDomain.objects.update_or_create(
                domain=str(spec["domain"]).lower(),
                defaults={
                    "institution": institution,
                    "allow_subdomains": bool(spec.get("allow_subdomains", False)),
                    "is_verified": verify_domains,
                },
            )
        for campus in record.get("campuses") or []:
            Campus.objects.update_or_create(
                institution=institution,
                slug=str(campus.get("slug") or slugify(campus["name"]))[:100],
                defaults={
                    "name": campus["name"],
                    "city": campus.get("city", ""),
                    "region": campus.get("region", ""),
                    "is_main": bool(campus.get("is_main", False)),
                },
            )
    return result
