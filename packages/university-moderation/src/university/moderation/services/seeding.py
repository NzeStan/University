from __future__ import annotations

from university.moderation.conf import moderation_settings
from university.moderation.models import ModerationRule, ReportReason


def sync_reasons_and_rules() -> None:
    """Seed configured reasons and rules (existing rows are left untouched)."""
    for position, spec in enumerate(moderation_settings.get("REASONS", [])):
        ReportReason.objects.get_or_create(
            key=spec["key"],
            defaults={
                "label": spec["label"],
                "description": spec.get("description", ""),
                "severity": spec.get("severity", "low"),
                "requires_details": bool(spec.get("requires_details", False)),
                "ordering": position,
            },
        )
    for spec in moderation_settings.get("DEFAULT_RULES", []):
        ModerationRule.objects.get_or_create(
            key=spec["key"],
            defaults={
                "name": spec["name"],
                "description": spec.get("description", ""),
                "rule_type": spec["rule_type"],
                "params": spec.get("params", {}),
                "action": spec.get("action", "hide"),
            },
        )
