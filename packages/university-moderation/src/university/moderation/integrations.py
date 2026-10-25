"""Hook implementations connecting moderation to Core (registered in apps.py)."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils import timezone

from university.moderation.constants import RestrictionKind


def can_create_content(user: Any, content_type: str) -> bool | None:
    """Active restrictions stop users creating the restricted kind of content."""
    from university.moderation.models import UserRestriction

    if user is None or not getattr(user, "is_authenticated", False):
        return None
    kinds = set(
        UserRestriction.objects.filter(user=user, lifted_at__isnull=True, ends_at__gt=timezone.now()).values_list(
            "kind", flat=True
        )
    )
    if not kinds:
        return None
    if RestrictionKind.ALL in kinds:
        return False
    if RestrictionKind.POSTING in kinds and content_type.endswith(".post"):
        return False
    if RestrictionKind.COMMENTING in kinds and content_type.endswith(".comment"):
        return False
    return None


def export_data(user: Any) -> dict[str, Any]:
    from university.moderation.models import ModerationAction, ModerationAppeal, Report, UserRestriction

    return {
        "moderation": {
            "reports_made": [
                {"content_type": r.case.content_type, "reason": r.reason.key, "created_at": r.created_at}
                for r in Report.objects.filter(reporter=user).select_related("case", "reason")
            ],
            "actions_received": [
                {"action": a.action, "reason": a.reason, "created_at": a.created_at, "reversed_at": a.reversed_at}
                for a in ModerationAction.objects.filter(target_user=user)
            ],
            "restrictions": [
                {"kind": r.kind, "ends_at": r.ends_at, "lifted_at": r.lifted_at}
                for r in UserRestriction.objects.filter(user=user)
            ],
            "appeals": [
                {"status": a.status, "statement": a.statement, "created_at": a.created_at}
                for a in ModerationAppeal.objects.filter(appellant=user)
            ],
        }
    }


def purge(user_id: Any) -> None:
    """Erase a purged user's reports and evidence snapshots of their content.

    Action records stay (accountability) but no longer carry personal text.
    """
    from university.moderation.models import ModerationCase, Report

    Report.objects.filter(reporter_id=user_id).delete()
    ModerationCase.objects.filter(Q(target_author_id=user_id)).update(excerpt="")
