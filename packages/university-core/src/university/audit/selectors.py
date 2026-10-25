"""Read-side queries for the audit log."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from django.db.models import QuerySet
from django.utils.dateparse import parse_datetime

from university.audit.actions import AuditCategory
from university.audit.models import AuditLog
from university.core.exceptions import ValidationError
from university.core.ids import is_valid_uuid

#: Filters an auditor may use. Anything else is ignored (no ORM injection).
ALLOWED_FILTERS = ("action", "category", "outcome", "actor", "target_type", "target_id", "scope_type", "scope_id")

#: Categories shown to users in their own activity history.
SELF_SERVICE_CATEGORIES = (AuditCategory.AUTH, AuditCategory.SECURITY, AuditCategory.ACCOUNT, AuditCategory.PRIVACY)


def _parse_dt(value: str, name: str) -> dt.datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValidationError(details={name: ["Invalid datetime."]})
    return parsed


def filter_audit_log(params: Mapping[str, Any]) -> QuerySet[AuditLog]:
    qs = AuditLog.objects.select_related("actor").all()
    for name in ALLOWED_FILTERS:
        value = params.get(name)
        if not value:
            continue
        if name == "actor":
            if not is_valid_uuid(value):
                raise ValidationError(details={"actor": ["Must be a UUID."]})
            qs = qs.filter(actor_ref=str(value))
        else:
            qs = qs.filter(**{name: str(value)[:100]})
    if params.get("since"):
        qs = qs.filter(created_at__gte=_parse_dt(params["since"], "since"))
    if params.get("until"):
        qs = qs.filter(created_at__lt=_parse_dt(params["until"], "until"))
    return qs.order_by("-created_at")


def activity_for_user(user: Any) -> QuerySet[AuditLog]:
    """A user's own security-relevant history (logins, password changes …)."""
    return AuditLog.objects.filter(actor_ref=str(user.pk), category__in=SELF_SERVICE_CATEGORIES).order_by("-created_at")
