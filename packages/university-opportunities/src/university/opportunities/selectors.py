"""Read side: who may see which opportunities, and discovery filters (whitelisted)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db.models import Q, QuerySet

from university.core.audiences import member_scopes_by_type
from university.opportunities.constants import OpportunityAudience, OpportunityStatus, PayPeriod
from university.opportunities.models import Opportunity

SORTS = {"newest": ("-published_at", "-id"), "deadline": ("deadline", "-published_at")}


def _authenticated(user: Any) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False))


def _audience_q(viewer: Any) -> Q:
    q = Q(audience=OpportunityAudience.PUBLIC)
    if _authenticated(viewer):
        institutions = member_scopes_by_type(viewer).get("institution", [])
        if institutions:
            q |= Q(audience=OpportunityAudience.INSTITUTION, scope_id__in=[str(i) for i in institutions])
    return q


def visible_opportunities(viewer: Any, params: Mapping[str, Any] | None = None) -> QuerySet[Opportunity]:
    params = params or {}
    qs = Opportunity.objects.filter(status=OpportunityStatus.OPEN, is_hidden=False).filter(_audience_q(viewer))
    if params.get("kind"):
        qs = qs.filter(kind=params["kind"])
    if params.get("work_mode"):
        qs = qs.filter(work_mode=params["work_mode"])
    if params.get("location"):
        qs = qs.filter(location__icontains=str(params["location"])[:120])
    if str(params.get("paid", "")).lower() in ("1", "true"):
        qs = qs.exclude(pay_period=PayPeriod.UNPAID)
    if params.get("institution"):
        qs = qs.filter(audience=OpportunityAudience.INSTITUTION, scope_id=str(params["institution"])[:64])
    if params.get("q"):
        term = str(params["q"])[:100]
        qs = qs.filter(Q(title__icontains=term) | Q(organization_name__icontains=term) | Q(description__icontains=term))
    return qs.order_by(*SORTS.get(str(params.get("sort", "")), SORTS["newest"])).select_related("poster")


def can_view(viewer: Any, opportunity: Opportunity) -> bool:
    if _authenticated(viewer) and opportunity.poster_id == viewer.pk:
        return True
    if opportunity.is_hidden or opportunity.deleted_at or opportunity.status == OpportunityStatus.DRAFT:
        return False
    if opportunity.audience == OpportunityAudience.PUBLIC:
        return True
    return _authenticated(viewer) and opportunity.scope_id in {
        str(i) for i in member_scopes_by_type(viewer).get("institution", [])
    }


def get_visible(viewer: Any, opportunity_id: Any) -> Opportunity:
    from university.core.exceptions import NotFound
    from university.core.ids import is_valid_uuid

    opportunity = (
        Opportunity.objects.select_related("poster").filter(pk=opportunity_id).first()
        if is_valid_uuid(opportunity_id)
        else None
    )
    if opportunity is None or not can_view(viewer, opportunity):
        raise NotFound()
    return opportunity
