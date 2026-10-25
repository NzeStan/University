"""Hook implementations connecting communities to Core (registered in apps.py)."""

from __future__ import annotations

import fnmatch
from typing import Any

from university.community.conf import community_settings
from university.community.constants import COMMUNITY_SCOPE, CommunityStatus, MembershipStatus, Privacy, Role
from university.core.ids import is_valid_uuid


def _active_memberships(user: Any) -> Any:
    from university.community.models import CommunityMembership

    return CommunityMembership.objects.filter(
        user=user,
        status=MembershipStatus.ACTIVE,
        community__status=CommunityStatus.ACTIVE,
        community__deleted_at__isnull=True,
    )


def scope_memberships(user: Any) -> list[tuple[str, Any]]:
    """Active members belong to the community audience."""
    return [(COMMUNITY_SCOPE, cid) for cid in _active_memberships(user).values_list("community_id", flat=True)]


def _role_codes(role: str) -> list[str]:
    return list((community_settings.get("ROLE_PERMISSIONS", {}) or {}).get(role, []))


def _matches(code: str, patterns: list[str]) -> bool:
    return any(p == code or fnmatch.fnmatchcase(code, p) for p in patterns)


def implicit_grants(user: Any, scope: Any) -> list[str]:
    """A role's permissions at its own community scope."""
    if scope.type != COMMUNITY_SCOPE or not getattr(user, "is_authenticated", False) or not is_valid_uuid(scope.id):
        return []
    role = _active_memberships(user).filter(community_id=scope.id).values_list("role", flat=True).first()
    return _role_codes(role) if role else []


def implicit_scopes(user: Any, code: str) -> list[tuple[str, Any]]:
    """Community scopes where the user's role implies ``code`` (for queue filters)."""
    if not getattr(user, "is_authenticated", False):
        return []
    roles = [r for r in Role.values if _matches(code, _role_codes(r))]
    if not roles:
        return []
    ids = _active_memberships(user).filter(role__in=roles).values_list("community_id", flat=True)
    return [(COMMUNITY_SCOPE, cid) for cid in ids]


def can_post(user: Any, scope_type: str, scope_id: Any, content_type: str) -> bool | None:
    """Enforce a community's posting and commenting policies."""
    from university.community.constants import POLICY_MIN_RANK, ROLE_RANK
    from university.community.models import Community

    if scope_type != COMMUNITY_SCOPE or not is_valid_uuid(scope_id):
        return None
    community = Community.objects.filter(pk=scope_id).values("posting_policy", "commenting_policy").first()
    if community is None:
        return False
    policy = community["commenting_policy"] if content_type.endswith(".comment") else community["posting_policy"]
    role = _active_memberships(user).filter(community_id=scope_id).values_list("role", flat=True).first()
    return ROLE_RANK.get(role, 0) >= POLICY_MIN_RANK.get(policy, 99)


def community_parents(community_id: Any) -> list[tuple[str, Any]]:
    """Linked communities sit under their parent audience (e.g. an institution)."""
    from university.community.models import Community

    if not is_valid_uuid(community_id):
        return []
    row = Community.all_objects.filter(pk=community_id).values_list("scope_type", "scope_id").first()
    return [row] if row and row[0] else []


def public_profile(target: Any, viewer: Any) -> dict[str, Any]:
    from university.users.services import get_privacy_settings

    if not get_privacy_settings(target).show_affiliations:
        return {}
    rows = (
        _active_memberships(target)
        .exclude(community__privacy=Privacy.PRIVATE)
        .select_related("community")
        .order_by("-joined_at")[:50]
    )
    return {
        "communities": [
            {"id": str(m.community_id), "name": m.community.name, "slug": m.community.slug, "role": m.role}
            for m in rows
        ]
    }


def export_data(user: Any) -> dict[str, Any]:
    from university.community.models import CommunityMembership

    return {
        "communities": [
            {"community": m.community.name, "role": m.role, "status": m.status, "joined_at": m.joined_at}
            for m in CommunityMembership.objects.filter(user=user).select_related("community")
        ]
    }


def purge(user_id: Any) -> None:
    """Remove a purged user's memberships; hand owned communities to a successor."""
    from django.db.models import Case, IntegerField, When

    from university.community.models import Community, CommunityMembership
    from university.community.services import _count

    for owned in CommunityMembership.objects.filter(user_id=user_id, role=Role.OWNER, status=MembershipStatus.ACTIVE):
        successor = (
            CommunityMembership.objects.filter(community_id=owned.community_id, status=MembershipStatus.ACTIVE)
            .exclude(user_id=user_id)
            .annotate(
                rank=Case(
                    When(role=Role.ADMIN, then=3),
                    When(role=Role.MODERATOR, then=2),
                    default=1,
                    output_field=IntegerField(),
                )
            )
            .order_by("-rank", "joined_at")
            .first()
        )
        owned.delete()
        _count(owned.community, -1)
        if successor is not None:
            CommunityMembership.objects.filter(pk=successor.pk).update(role=Role.OWNER)
        else:
            Community.objects.filter(pk=owned.community_id).update(status=CommunityStatus.ARCHIVED)
    for member in CommunityMembership.objects.filter(user_id=user_id, status=MembershipStatus.ACTIVE).select_related(
        "community"
    ):
        _count(member.community, -1)
    CommunityMembership.objects.filter(user_id=user_id).delete()
