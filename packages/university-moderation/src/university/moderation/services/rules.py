"""Automated moderation rules.

Rules only take reversible, content-level actions (hide), always record a
machine-readable explanation, and leave the case open so a human makes the
final decision. Each rule fires at most once per case.
"""

from __future__ import annotations

from typing import Any

from university.moderation.conf import moderation_settings
from university.moderation.constants import AUTOMATABLE_ACTIONS, RuleType
from university.moderation.models import ModerationAction, ModerationCase, ModerationRule

_SEVERITY_ORDER = ["low", "medium", "high", "critical"]


def _matches(rule: ModerationRule, case: ModerationCase, reason: Any) -> dict[str, Any] | None:
    if rule.rule_type == RuleType.REPORT_THRESHOLD:
        threshold = int(rule.params.get("threshold", 5))
        if case.report_count >= threshold:
            return {"report_count": case.report_count, "threshold": threshold}
    elif rule.rule_type == RuleType.SEVERITY:
        minimum = rule.params.get("severity", "critical")
        if _SEVERITY_ORDER.index(reason.severity) >= _SEVERITY_ORDER.index(minimum):
            return {"reason": reason.key, "severity": reason.severity, "minimum": minimum}
    return None


def evaluate_rules(case: ModerationCase, reason: Any) -> list[ModerationAction]:
    from university.moderation.services.actions import apply_automated_action

    applied = []
    for rule in ModerationRule.objects.filter(is_active=True).order_by("created_at"):
        if rule.action not in AUTOMATABLE_ACTIONS:
            continue
        if ModerationAction.objects.filter(case=case, rule=rule).exists():
            continue
        inputs = _matches(rule, case, reason)
        if inputs is None:
            continue
        explanation = {"rule": rule.key, "rule_type": rule.rule_type, "inputs": inputs}
        applied.append(apply_automated_action(case, rule, explanation))
    return applied


def severity_weight(severity: str) -> int:
    return int(moderation_settings.get("SEVERITY_WEIGHTS", {}).get(severity, 1))
