"""User reports.

Reporting reveals nothing: the response is the same whether or not others
have reported the item, and the target never learns who reported them.
Users can only report content they can see.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction

from university.core.content import get_moderatable_adapter
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, ValidationError
from university.core.ratelimit import rate_limit
from university.moderation import events
from university.moderation.conf import moderation_settings
from university.moderation.constants import CaseSource
from university.moderation.models import Report, ReportReason
from university.moderation.services.cases import bump_priority, get_or_open_case
from university.moderation.services.rules import evaluate_rules


@transaction.atomic
def report_content(*, reporter: Any, content_type: str, object_id: Any, reason: str, details: str = "") -> Report:
    rate_limit("report", key=str(reporter.pk))
    adapter = get_moderatable_adapter(content_type)
    ref = adapter.resolve(object_id)
    if ref is None or not adapter.can_view(reporter, object_id):
        raise NotFound("Content not found.")
    if adapter.is_author(object_id, reporter):
        raise ValidationError("You can't report your own content.", code="self_report")
    reason_obj = ReportReason.objects.filter(key=reason, is_active=True).first()
    if reason_obj is None:
        raise ValidationError(details={"reason": ["Unknown reason."]})
    details = (details or "").strip()[:1000]
    if reason_obj.requires_details and not details:
        raise ValidationError(details={"details": ["Please describe the problem."]})

    case, _ = get_or_open_case(adapter, ref, source=CaseSource.REPORT)
    try:
        with transaction.atomic():
            report = Report.objects.create(case=case, reporter=reporter, reason=reason_obj, details=details)
    except IntegrityError:
        raise Conflict("You have already reported this.", code="already_reported") from None
    weight = int(moderation_settings.get("SEVERITY_WEIGHTS", {}).get(reason_obj.severity, 1))
    bump_priority(case, weight)
    evaluate_rules(case, reason_obj)
    publish(events.REPORT_CREATED, {"case_id": case.pk, "content_type": case.content_type, "reason": reason_obj.key})
    return report
