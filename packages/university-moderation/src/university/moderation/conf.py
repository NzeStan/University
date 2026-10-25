"""Settings for the moderation module (``UNIVERSITY["MODERATION"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    # Seeded into ReportReason on migrate; editable in admin afterwards.
    "REASONS": [
        {"key": "spam", "label": "Spam or scam", "severity": "low"},
        {"key": "harassment", "label": "Harassment or bullying", "severity": "high"},
        {"key": "hate_speech", "label": "Hate speech", "severity": "high"},
        {"key": "violence", "label": "Threats or violence", "severity": "critical"},
        {"key": "sexual_content", "label": "Sexual content", "severity": "high"},
        {"key": "child_safety", "label": "Child safety", "severity": "critical"},
        {"key": "self_harm", "label": "Self-harm or suicide", "severity": "critical"},
        {"key": "privacy_violation", "label": "Sharing private information", "severity": "high"},
        {"key": "impersonation", "label": "Impersonation", "severity": "medium"},
        {"key": "misinformation", "label": "False information", "severity": "medium"},
        {"key": "academic_dishonesty", "label": "Exam leaks or academic dishonesty", "severity": "medium"},
        {"key": "illegal", "label": "Illegal activity", "severity": "high"},
        {"key": "other", "label": "Something else", "severity": "low", "requires_details": True},
    ],
    "SEVERITY_WEIGHTS": {"low": 1, "medium": 2, "high": 4, "critical": 8},
    # Seeded into ModerationRule on migrate. Rule types: report_threshold, severity.
    # Automated rules only take reversible content actions and leave the case
    # open for human review.
    "DEFAULT_RULES": [
        {
            "key": "report_threshold",
            "name": "Hide content reported by many people",
            "rule_type": "report_threshold",
            "params": {"threshold": 5},
            "action": "hide",
        },
        {
            "key": "critical_report",
            "name": "Hide content reported for a critical reason",
            "rule_type": "severity",
            "params": {"severity": "critical"},
            "action": "hide",
        },
    ],
    "APPEAL_WINDOW_DAYS": 14,
    # The decider of an appeal must differ from the moderator who acted.
    "APPEALS_REQUIRE_DIFFERENT_MODERATOR": True,
    "MAX_RESTRICTION_DAYS": 365,
    "RESOLVED_CASE_RETENTION_DAYS": 730,
    "EXCERPT_LENGTH": 500,
}

moderation_settings = ModuleSettings("MODERATION", DEFAULTS)
