"""Content adapter: communities themselves can be reported to platform moderation.

A report about a community goes to moderators of its *parent* scope (or the
platform) — never to the community's own moderators, who may be the problem.
"""

from __future__ import annotations

from typing import Any

from university.community.constants import CommunityStatus, Role
from university.community.models import Community, CommunityMembership
from university.core.content import ContentAdapter, ContentRef
from university.core.ids import is_valid_uuid


class CommunityAdapter(ContentAdapter):
    content_type = "community.community"
    moderatable = True
    label = "Community"

    def iter_ids(self) -> Any:
        """Live items, for search backfills."""
        from university.community.models import Community

        return (str(pk) for pk in Community.objects.filter(status="active").values_list("pk", flat=True).iterator())

    def _get(self, object_id: Any) -> Community | None:
        return Community.objects.filter(pk=object_id).first() if is_valid_uuid(object_id) else None

    def resolve(self, object_id: Any) -> ContentRef | None:
        community = self._get(object_id)
        if community is None:
            return None
        owner_id = (
            CommunityMembership.objects.filter(community=community, role=Role.OWNER)
            .values_list("user_id", flat=True)
            .first()
        )
        return ContentRef(
            content_type=self.content_type,
            object_id=str(community.pk),
            author_id=str(owner_id) if owner_id else None,
            scope=community.parent_scope,
            excerpt=f"{community.name}\n{community.description}"[:500],
            status=community.status,
            created_at=community.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        from university.community.selectors import can_view

        community = self._get(object_id)
        return community is not None and can_view(viewer, community)

    def hide(self, object_id: Any, *, reason: str) -> None:
        Community.objects.filter(pk=object_id).update(status=CommunityStatus.SUSPENDED, status_reason=reason[:255])

    def restore(self, object_id: Any) -> None:
        Community.all_objects.filter(pk=object_id).update(
            status=CommunityStatus.ACTIVE, status_reason="", deleted_at=None
        )

    def remove(self, object_id: Any, *, reason: str) -> None:
        community = self._get(object_id)
        if community is not None:
            Community.objects.filter(pk=community.pk).update(status_reason=reason[:255])
            community.delete()
