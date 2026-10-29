"""Content adapter for institutions — display only.

It lets other modules name an institution and check whether someone may see
it (for example "Your membership of Example University was verified." in a
notification) without importing this module.

Institutions are deliberately **not moderatable**: they can't be reported,
and moderation can't open cases or take actions on them. Enabling that is a
separate policy decision. It would need to define who investigates reports
about an institution (platform trust & safety, not the institution's own
staff) and which actions are allowed, and then implement them here before
setting ``moderatable = True``.
"""

from __future__ import annotations

from typing import Any

from university.core.content import ContentAdapter, ContentRef
from university.core.ids import is_valid_uuid
from university.institution.constants import INSTITUTION_SCOPE, InstitutionStatus


class InstitutionAdapter(ContentAdapter):
    content_type = "institution.institution"
    label = "Institution"
    moderatable = False

    def _get(self, object_id: Any) -> Any:
        from university.institution.models import Institution

        if not is_valid_uuid(object_id):
            return None
        return Institution.objects.filter(pk=object_id).first()

    def resolve(self, object_id: Any) -> ContentRef | None:
        institution = self._get(object_id)
        if institution is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(institution.pk),
            author_id=None,
            scope=(INSTITUTION_SCOPE, str(institution.pk)),
            excerpt=institution.name,
            status=institution.status,
            created_at=institution.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        """Same rule as the institution API: active institutions are public."""
        from university.institution.selectors import can_manage

        institution = self._get(object_id)
        if institution is None:
            return False
        if institution.status == InstitutionStatus.ACTIVE:
            return True
        return bool(
            viewer is not None and viewer.is_authenticated and can_manage(viewer, institution, "institution.edit")
        )


class AnnouncementAdapter(ContentAdapter):
    """Official announcements: display only, like institutions themselves.

    They are **not moderatable** for the same reason as institutions: reporting an institution's
    official notice needs its own policy (who investigates: platform trust & safety, never the
    institution's staff; which actions are allowed). Until that policy exists, announcements can be
    shown, searched and linked to, but not reported.
    """

    content_type = "institution.announcement"
    label = "Announcement"
    moderatable = False

    def _get(self, object_id: Any) -> Any:
        from university.institution.models import Announcement

        if not is_valid_uuid(object_id):
            return None
        return Announcement.objects.select_related("institution").filter(pk=object_id).first()

    def iter_ids(self) -> Any:
        from university.institution.models import Announcement

        live = Announcement.objects.filter(status="published", audience="public").values_list("pk", flat=True)
        return (str(pk) for pk in live.iterator())

    def resolve(self, object_id: Any) -> ContentRef | None:
        announcement = self._get(object_id)
        if announcement is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(announcement.pk),
            author_id=None,
            scope=(INSTITUTION_SCOPE, str(announcement.institution_id)),
            excerpt=(announcement.title + "\n" + announcement.body)[:500],
            status=announcement.status,
            created_at=announcement.published_at or announcement.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        from university.institution.selectors import can_view_announcement

        announcement = self._get(object_id)
        return announcement is not None and can_view_announcement(viewer, announcement)
