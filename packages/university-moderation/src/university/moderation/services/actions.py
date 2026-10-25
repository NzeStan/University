"""Moderation actions and their reversal.

Authorisation:

* content actions (dismiss, warn, hide, remove, restore) — ``moderation.cases.act``
  at the case's scope (a platform grant applies everywhere);
* ``restrict`` — additionally ``moderation.users.restrict`` (platform);
* ``suspend`` / ``ban`` — additionally Core's ``users.suspend`` / ``users.ban``
  (enforced by the users services);
* any user-level action on **anonymous** content — additionally the adapter's
  ``sanction_permission``, because it links author and content in the
  moderation record (audited as such).

Moderators can never act on their own content (conflict of interest).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db import transaction
from django.utils import timezone

from university.audit.services import record as audit
from university.core.content import get_adapter, get_moderatable_adapter
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.moderation import events
from university.moderation.conf import moderation_settings
from university.moderation.constants import (
    CONTENT_ACTIONS,
    USER_ACTIONS,
    Action,
    CaseStatus,
    RestrictionKind,
)
from university.moderation.models import ModerationAction, ModerationCase, ModerationRule, UserRestriction
from university.moderation.services.cases import case_scope
from university.permissions.services import authorize


def _event_payload(action: ModerationAction, case: ModerationCase | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action_id": action.pk,
        "action": action.action,
        "content_type": action.content_type,
        "object_id": action.object_id,
        "case_id": case.pk if case else None,
        "automated": action.automated,
    }
    if not (case and case.target_is_anonymous):
        payload["target_user_id"] = action.target_user_id
    return payload


def _audit(action: ModerationAction, case: ModerationCase | None, actor: Any) -> None:
    audit(
        f"moderation.action.{action.action}",
        actor=actor,
        target=action,
        category="moderation",
        scope=case.scope if case else None,
        metadata={
            "case_id": str(case.pk) if case else None,
            "content_type": action.content_type,
            "object_id": action.object_id,
            "automated": action.automated,
            "reason": action.reason,
        },
    )


def _resolve_target_user(actor: Any, case: ModerationCase, adapter: Any) -> Any:
    if not case.target_is_anonymous:
        return case.target_author
    if not adapter.sanction_permission:
        raise PermissionDenied()
    authorize(actor, adapter.sanction_permission, case_scope(case), audit_denial=True)
    user = adapter.resolve_author(case.object_id)
    audit(
        "anonymous.identity.used_for_sanction",
        actor=actor,
        target=case,
        category="security",
        metadata={"content_type": case.content_type, "object_id": case.object_id},
    )
    return user


def _is_conflicted(actor: Any, case: ModerationCase, adapter: Any) -> bool:
    if case.target_author_id is not None:
        return case.target_author_id == actor.pk
    return case.target_is_anonymous and adapter.is_author(case.object_id, actor)


@transaction.atomic
def take_action(
    *,
    actor: Any,
    case_id: Any,
    action: str,
    reason: str,
    duration_hours: int | None = None,
    restriction_kind: str = RestrictionKind.POSTING,
) -> ModerationAction:
    case = ModerationCase.objects.select_for_update().filter(pk=case_id).first()
    if case is None:
        raise NotFound("Case not found.")
    if action not in Action.values:
        raise ValidationError(details={"action": ["Unknown action."]})
    scope = case_scope(case)
    authorize(actor, "moderation.cases.act", scope, audit_denial=True)
    if action == Action.RESTRICT:
        authorize(actor, "moderation.users.restrict", audit_denial=True)
    adapter = get_moderatable_adapter(case.content_type)
    if _is_conflicted(actor, case, adapter):
        raise PermissionDenied("You can't moderate your own content.", code="conflict_of_interest")

    target_user = None
    expires_at = None
    if action in USER_ACTIONS:
        target_user = _resolve_target_user(actor, case, adapter)
        if target_user is None:
            raise ValidationError("This content has no author to act on.", code="no_author")
    elif not case.target_is_anonymous:
        target_user = case.target_author  # lets the author see and appeal content actions

    if action == Action.HIDE:
        adapter.hide(case.object_id, reason=reason)
    elif action == Action.REMOVE:
        adapter.remove(case.object_id, reason=reason)
    elif action == Action.RESTORE:
        adapter.restore(case.object_id)
    elif action == Action.RESTRICT:
        max_hours = int(moderation_settings.get("MAX_RESTRICTION_DAYS", 365)) * 24
        if not duration_hours or not 1 <= int(duration_hours) <= max_hours:
            raise ValidationError(details={"duration_hours": [f"Between 1 and {max_hours} hours."]})
        if restriction_kind not in RestrictionKind.values:
            raise ValidationError(details={"restriction_kind": ["Unknown restriction."]})
        expires_at = timezone.now() + dt.timedelta(hours=int(duration_hours))
    elif action == Action.SUSPEND:
        from university.users.services import suspend_user

        if duration_hours:
            expires_at = timezone.now() + dt.timedelta(hours=int(duration_hours))
        suspend_user(actor=actor, user=target_user, reason=reason or "Moderation", until=expires_at)
    elif action == Action.BAN:
        from university.users.services import ban_user

        ban_user(actor=actor, user=target_user, reason=reason or "Moderation")

    record = ModerationAction.objects.create(
        case=case,
        action=action,
        content_type=case.content_type,
        object_id=case.object_id,
        target_user=target_user,
        actor=actor,
        reason=reason[:500],
        expires_at=expires_at,
    )
    if action == Action.RESTRICT:
        UserRestriction.objects.create(
            user=target_user, kind=restriction_kind, ends_at=expires_at, action=record, reason=reason[:500]
        )
    case.status = CaseStatus.DISMISSED if action == Action.DISMISS else CaseStatus.ACTIONED
    case.resolved_at = timezone.now()
    case.resolved_by = actor
    case.resolution = action
    case.save(update_fields=["status", "resolved_at", "resolved_by", "resolution", "updated_at"])
    _audit(record, case, actor)
    publish(events.ACTION_TAKEN, _event_payload(record, case), actor=actor)
    return record


def apply_automated_action(case: ModerationCase, rule: ModerationRule, explanation: dict[str, Any]) -> ModerationAction:
    adapter = get_moderatable_adapter(case.content_type)
    if rule.action == Action.HIDE:
        adapter.hide(case.object_id, reason=f"Automated: {rule.name}")
    record = ModerationAction.objects.create(
        case=case,
        action=rule.action,
        content_type=case.content_type,
        object_id=case.object_id,
        target_user=None if case.target_is_anonymous else case.target_author,
        automated=True,
        rule=rule,
        reason=f"Automated: {rule.name}"[:500],
        explanation=explanation,
    )
    ModerationCase.objects.filter(pk=case.pk).update(auto_actioned=True)
    case.auto_actioned = True
    _audit(record, case, None)
    publish(events.ACTION_TAKEN, _event_payload(record, case))
    return record


@transaction.atomic
def reverse_action(*, actor: Any, action: ModerationAction, reason: str) -> ModerationAction:
    """Undo an action's effects (used by appeals and by moderators)."""
    if action.reversed_at is not None:
        raise Conflict("This action was already reversed.", code="already_reversed")
    if action.action in CONTENT_ACTIONS - {Action.RESTORE}:
        # Undoing a past decision stays possible even if the type later opts out of moderation.
        get_adapter(action.content_type).restore(action.object_id)
    elif action.action == Action.RESTRICT:
        UserRestriction.objects.filter(action=action, lifted_at__isnull=True).update(lifted_at=timezone.now())
    elif action.action in (Action.SUSPEND, Action.BAN) and action.target_user is not None:
        from university.users.services import reactivate_user

        reactivate_user(actor=actor, user=action.target_user, reason=reason)
    action.reversed_at = timezone.now()
    action.reversed_by = actor
    action.reversal_reason = reason[:500]
    action.save(update_fields=["reversed_at", "reversed_by", "reversal_reason", "updated_at"])
    audit(
        "moderation.action.reversed",
        actor=actor,
        target=action,
        category="moderation",
        metadata={"action": action.action, "reason": reason[:500]},
    )
    publish(events.ACTION_REVERSED, _event_payload(action, action.case), actor=actor)
    return action


@transaction.atomic
def lift_restriction(*, actor: Any, restriction_id: Any, reason: str = "") -> UserRestriction:
    authorize(actor, "moderation.users.restrict", audit_denial=True)
    restriction = UserRestriction.objects.select_for_update().filter(pk=restriction_id, lifted_at__isnull=True).first()
    if restriction is None:
        raise NotFound("Restriction not found.")
    restriction.lifted_at = timezone.now()
    restriction.save(update_fields=["lifted_at", "updated_at"])
    audit(
        "moderation.restriction.lifted",
        actor=actor,
        target=restriction,
        category="moderation",
        metadata={"reason": reason},
    )
    return restriction
