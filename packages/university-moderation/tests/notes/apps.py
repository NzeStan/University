"""A stand-in content module registering two content types with Core."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from university.core.content import ContentAdapter, ContentRef
from university.core.declarations import PermissionDef, ScopeTypeDef
from university.core.hooks import Hook, HookRegistry
from university.core.ids import is_valid_uuid
from university.core.modules import UniversityAppConfig


class NoteAdapter(ContentAdapter):
    content_type = "notes.note"
    moderatable = True
    anonymous = False

    def _get(self, object_id: Any) -> Any:
        from tests.notes.models import Note

        if not is_valid_uuid(object_id):
            return None
        return Note.objects.filter(pk=object_id, anonymous=self.anonymous).first()

    def resolve(self, object_id: Any) -> ContentRef | None:
        note = self._get(object_id)
        if note is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(note.pk),
            author_id=None if self.anonymous else str(note.author_id),
            is_anonymous=self.anonymous,
            scope=(note.scope_type, note.scope_id) if note.scope_type else None,
            excerpt=note.body,
            status="removed" if note.removed else "hidden" if note.hidden else "published",
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        note = self._get(object_id)
        return note is not None and not note.removed and (not note.hidden or note.author_id == viewer.pk)

    def hide(self, object_id: Any, *, reason: str) -> None:
        self._update(object_id, hidden=True)

    def restore(self, object_id: Any) -> None:
        self._update(object_id, hidden=False, removed=False)

    def remove(self, object_id: Any, *, reason: str) -> None:
        self._update(object_id, removed=True)

    def _update(self, object_id: Any, **fields: Any) -> None:
        from tests.notes.models import Note

        Note.objects.filter(pk=object_id).update(**fields)

    def is_author(self, object_id: Any, user: Any) -> bool:
        note = self._get(object_id)
        return note is not None and note.author_id == user.pk

    def resolve_author(self, object_id: Any) -> Any:
        note = self._get(object_id)
        return note.author if note else None


class AnonymousNoteAdapter(NoteAdapter):
    content_type = "notes.anonymous_note"
    anonymous = True
    sanction_permission = "notes.authors.sanction"


class NotesConfig(UniversityAppConfig):
    name = "tests.notes"
    label = "notes"
    module_name = "notes"

    def get_content_adapters(self) -> list[Any]:
        return [NoteAdapter(), AnonymousNoteAdapter()]

    def get_scope_types(self) -> Iterable[ScopeTypeDef]:
        return [ScopeTypeDef("institution")]

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [PermissionDef("notes.authors.sanction", "Sanction anonymous authors.", sensitive=True)]

    def register_hooks(self, hooks: HookRegistry) -> None:
        hooks.register(Hook.USER_CAN_CREATE_CONTENT, lambda user, content_type: None)
