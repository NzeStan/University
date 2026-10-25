"""Read side of moderation: scope-filtered queues and the user's own records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db.models import Q, QuerySet

from university.core.exceptions import NotFound
from university.core.ids import is_valid_uuid
from university.moderation.constants import AppealStatus, CaseStatus
from university.moderation.models import ModerationAction, ModerationAppeal, ModerationCase, Report
from university.moderation.services.cases import case_scope
from university.permissions.services import authorize, scopes_with_permission


def _scope_filter(user: Any, code: str, prefix: str = "") -> Q | None:
    """``None`` = everything; otherwise a Q limiting rows to granted scopes."""
    scopes = scopes_with_permission(user, code)
    if scopes is None:
        return None
    q = Q(pk__in=[])
    for scope in scopes:
        q |= Q(**{f"{prefix}scopes__scope_type": scope.type, f"{prefix}scopes__scope_id": scope.id})
    return q


def moderation_queue(user: Any, params: Mapping[str, Any]) -> QuerySet[ModerationCase]:
    qs = ModerationCase.objects.select_related("target_author", "assigned_to")
    scope_q = _scope_filter(user, "moderation.cases.view")
    if scope_q is not None:
        qs = qs.filter(scope_q).distinct()
    status = params.get("status", CaseStatus.OPEN)
    if status in CaseStatus.values:
        qs = qs.filter(status=status)
    if params.get("content_type"):
        qs = qs.filter(content_type=str(params["content_type"])[:64])
    if params.get("scope_type") and params.get("scope_id"):
        qs = qs.filter(scopes__scope_type=str(params["scope_type"])[:32], scopes__scope_id=str(params["scope_id"])[:64])
    if params.get("assigned") == "me":
        qs = qs.filter(assigned_to=user)
    return qs.order_by("-priority", "created_at", "id")


def get_case_for_moderator(user: Any, case_id: Any) -> ModerationCase:
    if not is_valid_uuid(case_id):
        raise NotFound("Case not found.")
    case = ModerationCase.objects.select_related("target_author", "assigned_to").filter(pk=case_id).first()
    if case is None:
        raise NotFound("Case not found.")
    authorize(user, "moderation.cases.view", case_scope(case))
    return case


def appeal_queue(user: Any, params: Mapping[str, Any]) -> QuerySet[ModerationAppeal]:
    qs = ModerationAppeal.objects.select_related("action", "action__case")
    scope_q = _scope_filter(user, "moderation.appeals.decide", prefix="action__case__")
    if scope_q is not None:
        qs = qs.filter(scope_q).distinct()
    status = params.get("status", AppealStatus.PENDING)
    if status in AppealStatus.values:
        qs = qs.filter(status=status)
    return qs.order_by("created_at", "id")


def my_reports(user: Any) -> QuerySet[Report]:
    return Report.objects.filter(reporter=user).select_related("case", "reason").order_by("-created_at")


def my_actions(user: Any) -> QuerySet[ModerationAction]:
    return ModerationAction.objects.filter(target_user=user).select_related("appeal").order_by("-created_at")


def my_appeals(user: Any) -> QuerySet[ModerationAppeal]:
    return ModerationAppeal.objects.filter(appellant=user).select_related("action").order_by("-created_at")
