"""Appeals: the affected user contests an action; a different moderator decides."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from university.audit.services import record as audit
from university.core.content import get_adapter
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.moderation import events
from university.moderation.conf import moderation_settings
from university.moderation.constants import APPEALABLE_ACTIONS, AppealStatus
from university.moderation.models import ModerationAction, ModerationAppeal
from university.moderation.services.actions import reverse_action
from university.moderation.services.cases import case_scope
from university.permissions.services import authorize


def _affects(user: Any, action: ModerationAction) -> bool:
    if action.target_user_id is not None:
        return action.target_user_id == user.pk
    # Anonymous content: the author proves authorship without being stored.
    try:
        return get_adapter(action.content_type).is_author(action.object_id, user)
    except Exception:
        return False


def _find_action(user: Any, action_id: Any, content_type: str | None, object_id: Any) -> ModerationAction:
    qs = ModerationAction.objects.select_related("case").filter(reversed_at__isnull=True, action__in=APPEALABLE_ACTIONS)
    if action_id:
        action = qs.filter(pk=action_id).first()
    elif content_type and object_id:
        action = qs.filter(content_type=content_type, object_id=str(object_id)).order_by("-created_at").first()
    else:
        raise ValidationError("Identify the action or the content to appeal.", code="appeal_target_required")
    # Unknown and not-yours are indistinguishable.
    if action is None or not _affects(user, action):
        raise NotFound("Nothing to appeal.")
    return action


@transaction.atomic
def file_appeal(
    *, user: Any, statement: str, action_id: Any = None, content_type: str | None = None, object_id: Any = None
) -> ModerationAppeal:
    action = _find_action(user, action_id, content_type, object_id)
    window = int(moderation_settings.get("APPEAL_WINDOW_DAYS", 14))
    if action.created_at < timezone.now() - dt.timedelta(days=window):
        raise ValidationError("The appeal window has closed.", code="appeal_window_closed")
    statement = (statement or "").strip()
    if not 10 <= len(statement) <= 2000:
        raise ValidationError(details={"statement": ["Explain your appeal in 10 to 2000 characters."]})
    try:
        with transaction.atomic():
            appeal = ModerationAppeal.objects.create(action=action, appellant=user, statement=statement)
    except IntegrityError:
        raise Conflict("This action has already been appealed.", code="already_appealed") from None
    audit("moderation.appeal.filed", actor=user, target=appeal, category="moderation")
    publish(events.APPEAL_FILED, {"appeal_id": appeal.pk, "action_id": action.pk})
    return appeal


@transaction.atomic
def decide_appeal(*, actor: Any, appeal_id: Any, overturn: bool, reason: str) -> ModerationAppeal:
    appeal = (
        ModerationAppeal.objects.select_for_update()
        .select_related("action", "action__case", "action__target_user")
        .filter(pk=appeal_id)
        .first()
    )
    if appeal is None:
        raise NotFound("Appeal not found.")
    action = appeal.action
    scope = case_scope(action.case) if action.case else None
    authorize(actor, "moderation.appeals.decide", scope, audit_denial=True)
    if appeal.status != AppealStatus.PENDING:
        raise Conflict("This appeal was already decided.", code="already_decided")
    if appeal.appellant_id == actor.pk:
        raise PermissionDenied("You can't decide your own appeal.", code="conflict_of_interest")
    if moderation_settings.get("APPEALS_REQUIRE_DIFFERENT_MODERATOR", True) and action.actor_id == actor.pk:
        raise PermissionDenied("A different moderator must review this appeal.", code="four_eyes_required")
    if overturn:
        reverse_action(actor=actor, action=action, reason=f"Appeal overturned: {reason}")
    appeal.status = AppealStatus.OVERTURNED if overturn else AppealStatus.UPHELD
    appeal.decided_by = actor
    appeal.decided_at = timezone.now()
    appeal.decision_reason = reason[:500]
    appeal.save(update_fields=["status", "decided_by", "decided_at", "decision_reason", "updated_at"])
    audit(
        "moderation.appeal.decided",
        actor=actor,
        target=appeal,
        category="moderation",
        metadata={"outcome": appeal.status, "action_id": str(action.pk)},
    )
    payload: dict[str, Any] = {"appeal_id": appeal.pk, "outcome": appeal.status}
    # Anonymous authors are never linked to their content in event payloads.
    if action.target_user_id is not None:
        payload["appellant_id"] = appeal.appellant_id
    publish(events.APPEAL_DECIDED, payload, actor=actor)
    return appeal
