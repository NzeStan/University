"""Settings for the analytics module (``UNIVERSITY["ANALYTICS"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    # Event-name patterns (fnmatch) that become daily metrics.
    "TRACK": [
        "user.created",
        "user.verified",
        "user.logged_in",
        "social.*",
        "anonymous.post.created",
        "anonymous.comment.created",
        "community.*",
        "institution.*",
        "events.*",
        "marketplace.*",
        "payments.payment.succeeded",
        "creator.*",
        "podcast.episode.published",
        "moderation.report.created",
        "moderation.action.taken",
        "content.viewed",
    ],
    # Never counted, even if a TRACK pattern matches.
    "EXCLUDE": ["*.notice", "notifications.*", "security.*", "events.attendee.*"],
    # Payload keys that add a per-scope breakdown: {payload key: scope type}.
    # Payloads with scope_type/scope_id are broken down by that scope too.
    "DIMENSIONS": {"institution_id": "institution", "community_id": "community", "campus_id": "campus"},
    # Count unique daily/weekly/monthly active users (keyed hashes in the cache; needs a shared cache).
    "ACTIVE_USERS": True,
    # Scope dashboards hide counts below this (small groups could be re-identified).
    "MIN_REPORTABLE": 5,
    # Repeat views of the same item by the same viewer within this window count once.
    "VIEW_DEDUPE_HOURS": 24,
    # Daily counters are kept this long.
    "RETENTION_DAYS": 1095,
    "MAX_RANGE_DAYS": 366,
    # Raw-event sinks (dotted paths to AnalyticsSink classes), e.g. "university.analytics.sinks.LogSink".
    "SINKS": [],
}

analytics_settings = ModuleSettings("ANALYTICS", DEFAULTS)
