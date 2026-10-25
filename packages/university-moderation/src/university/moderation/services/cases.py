"""Case lifecycle: opening (from reports or manually) and assignment."""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F

from university.audit.services import record as audit
from university.core.content import ContentAdapter, ContentRef, get_moderatable_adapter
from university.core.events import publish
from university.core.exceptions import NotFound
from university.moderation import events
from university.moderation.conf import moderation_settings
from university.moderation.constants import CaseSource, CaseStatus
from university.moderation.models import CaseScope, ModerationCase
from university.permissions.scopes import Scope
from university.permissions.services import authorize, scope_chain


def case_scope(case: ModerationCase) -> Scope | None:
    return Scope(case.scope_type, case.scope_id) if case.scope_type else None


def get_or_open_case(adapter: ContentAdapter, ref: ContentRef, *, source: str) -> tuple[ModerationCase, bool]:
    """The open case for a content item, creating it if needed (race-safe)."""
    existing = (
        ModerationCase.objects.select_for_update()
        .filter(content_type=ref.content_type, object_id=ref.object_id, status=CaseStatus.OPEN)
        .first()
    )
    if existing is not None:
        return existing, False
    scope_type, scope_id = ref.scope or ("", "")
    try:
        with transaction.atomic():
            case = ModerationCase.objects.create(
                content_type=ref.content_type,
                object_id=ref.object_id,
                scope_type=scope_type,
                scope_id=scope_id,
                source=source,
                target_author_id=None if ref.is_anonymous else ref.author_id,
                target_is_anonymous=ref.is_anonymous,
                excerpt=ref.excerpt[: int(moderation_settings.get("EXCERPT_LENGTH", 500))],
            )
    except IntegrityError:
        return ModerationCase.objects.select_for_update().get(
            content_type=ref.content_type, object_id=ref.object_id, status=CaseStatus.OPEN
        ), False
    if ref.scope:
        CaseScope.objects.bulk_create(
            [CaseScope(case=case, scope_type=s.type, scope_id=s.id) for s in scope_chain(Scope(*ref.scope))],
            ignore_conflicts=True,
        )
    publish(
        events.CASE_OPENED,
        {"case_id": case.pk, "content_type": case.content_type, "object_id": case.object_id, "source": source},
    )
    return case, True


@transaction.atomic
def open_case(*, actor: Any, content_type: str, object_id: Any, note: str = "") -> ModerationCase:
    """A moderator opens a case proactively (without a user report)."""
    adapter = get_moderatable_adapter(content_type)
    ref = adapter.resolve(object_id)
    if ref is None:
        raise NotFound("Content not found.")
    authorize(actor, "moderation.cases.act", Scope(*ref.scope) if ref.scope else None, audit_denial=True)
    case, _ = get_or_open_case(adapter, ref, source=CaseSource.MANUAL)
    audit("moderation.case.opened", actor=actor, target=case, category="moderation", metadata={"note": note[:500]})
    return case


@transaction.atomic
def assign_case(*, actor: Any, case_id: Any) -> ModerationCase:
    case = ModerationCase.objects.select_for_update().filter(pk=case_id).first()
    if case is None:
        raise NotFound("Case not found.")
    authorize(actor, "moderation.cases.act", case_scope(case))
    ModerationCase.objects.filter(pk=case.pk).update(assigned_to=actor)
    case.assigned_to = actor
    return case


def bump_priority(case: ModerationCase, severity_weight: int) -> None:
    weight = max(case.max_severity_weight, severity_weight)
    ModerationCase.objects.filter(pk=case.pk).update(
        report_count=F("report_count") + 1,
        max_severity_weight=weight,
        priority=weight * 10 + F("report_count") + 1,
    )
    case.refresh_from_db(fields=["report_count", "max_severity_weight", "priority"])
