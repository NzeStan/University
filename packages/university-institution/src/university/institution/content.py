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
