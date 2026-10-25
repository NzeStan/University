"""Read side of communities.

Private communities are invisible (404) to anyone who is not an active or
invited member — their existence is never confirmed to outsiders.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db.models import Q, QuerySet

from university.community.constants import (
    COMMUNITY_SCOPE,
    MANAGER_RANK,
    ROLE_RANK,
    CommunityStatus,
    MembershipStatus,
    Privacy,
    Role,
)
from university.community.models import Community, CommunityMembership
from university.core.exceptions import NotFound
from university.core.ids import is_valid_uuid
from university.permissions.scopes import Scope
from university.permissions.services import has_permission


def _auth(user: Any) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False))


def scope_of(community: Community) -> Scope:
    return Scope(COMMUNITY_SCOPE, community.pk)


def membership(user: Any, community: Community) -> CommunityMembership | None:
    if not _auth(user):
        return None
    return CommunityMembership.objects.filter(community=community, user=user).first()


def rank(user: Any, community: Community) -> int:
    """Authority within a community: member < moderator < admin < owner < manager."""
    member = membership(user, community)
    member_rank = ROLE_RANK.get(member.role, 0) if member and member.status == MembershipStatus.ACTIVE else 0
    if member_rank != ROLE_RANK[Role.OWNER] and has_permission(user, "community.manage", scope_of(community)):
        return MANAGER_RANK
    return member_rank


def visible_communities(viewer: Any) -> QuerySet[Community]:
    qs = Community.objects.exclude(status=CommunityStatus.SUSPENDED)
    if _auth(viewer) and has_permission(viewer, "community.manage"):
        return Community.objects.all()
    visible = Q(privacy__in=[Privacy.PUBLIC, Privacy.RESTRICTED])
    if _auth(viewer):
        visible |= Q(
            memberships__user=viewer, memberships__status__in=[MembershipStatus.ACTIVE, MembershipStatus.INVITED]
        )
    return qs.filter(visible).distinct()


def get_visible_community(viewer: Any, community_id: Any) -> Community:
    if not is_valid_uuid(community_id):
        raise NotFound("Community not found.")
    community = Community.all_objects.filter(pk=community_id, deleted_at__isnull=True).first()
    if community is None or not can_view(viewer, community):
        raise NotFound("Community not found.")
    return community


def can_view(viewer: Any, community: Community) -> bool:
    if _auth(viewer) and has_permission(viewer, "community.manage", scope_of(community)):
        return True
    if community.status == CommunityStatus.SUSPENDED:
        return False
    if community.privacy != Privacy.PRIVATE:
        return True
    member = membership(viewer, community)
    return member is not None and member.status in (MembershipStatus.ACTIVE, MembershipStatus.INVITED)


def search(viewer: Any, params: Mapping[str, Any]) -> QuerySet[Community]:
    qs = visible_communities(viewer).filter(status=CommunityStatus.ACTIVE)
    if params.get("q"):
        term = str(params["q"]).strip()[:100]
        qs = qs.filter(Q(name__icontains=term) | Q(description__icontains=term))
    if params.get("kind"):
        qs = qs.filter(kind=str(params["kind"])[:32])
    if params.get("scope_type") and params.get("scope_id"):
        qs = qs.filter(scope_type=str(params["scope_type"])[:32], scope_id=str(params["scope_id"])[:64])
    if params.get("official") in ("true", "1"):
        qs = qs.filter(is_official=True)
    return qs.order_by("-member_count", "name", "id")


def members(community: Community, params: Mapping[str, Any]) -> QuerySet[CommunityMembership]:
    qs = CommunityMembership.objects.filter(community=community, status=MembershipStatus.ACTIVE, user__status="active")
    if params.get("role") in Role.values:
        qs = qs.filter(role=params["role"])
    return qs.select_related("user").order_by("-joined_at", "id")


def my_communities(user: Any) -> QuerySet[CommunityMembership]:
    return (
        CommunityMembership.objects.filter(user=user, status=MembershipStatus.ACTIVE)
        .exclude(community__status=CommunityStatus.SUSPENDED)
        .filter(community__deleted_at__isnull=True)
        .select_related("community")
        .order_by("-joined_at")
    )
