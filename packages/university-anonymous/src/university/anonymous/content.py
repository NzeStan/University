"""Content adapters exposing anonymous items to moderation — without authors.

``resolve`` always returns ``author_id=None``. ``resolve_author`` decrypts the
identity and exists solely for authorised sanctions; moderation guards it
with :attr:`sanction_permission` and audits each use.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model

from university.anonymous.identity import open_identity, owns
from university.anonymous.models import AnonymousComment, AnonymousPost, Authorship, ContentStatus
from university.anonymous.selectors import can_view_post
from university.core.content import ContentAdapter, ContentRef
from university.core.ids import is_valid_uuid


class _AnonymousAdapter(ContentAdapter):
    moderatable = True
    kind: str = ""
    model: Any = None
    sanction_permission = "anonymous.authors.sanction"

    def iter_ids(self) -> Any:
        """Live items, for search backfills."""
        return (str(pk) for pk in self.model.objects.filter(status="published").values_list("pk", flat=True).iterator())

    def _get(self, object_id: Any, *, include_deleted: bool = False) -> Any:
        if not is_valid_uuid(object_id):
            return None
        manager = self.model.all_objects if include_deleted else self.model.objects
        return manager.filter(pk=object_id).first()

    def _scope(self, obj: Any) -> tuple[str, str] | None:
        post = obj if isinstance(obj, AnonymousPost) else obj.post
        return (post.scope_type, post.scope_id) if post.scope_type else None

    def resolve(self, object_id: Any) -> ContentRef | None:
        obj = self._get(object_id)
        if obj is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(obj.pk),
            author_id=None,
            is_anonymous=True,
            scope=self._scope(obj),
            excerpt=obj.body[:500],
            status=obj.status,
            created_at=obj.created_at,
        )

    def is_author(self, object_id: Any, user: Any) -> bool:
        record = (
            Authorship.objects.filter(kind=self.kind, object_id=object_id).first() if is_valid_uuid(object_id) else None
        )
        return record is not None and owns(self.kind, object_id, user, record.owner_token)

    def resolve_author(self, object_id: Any) -> Any:
        record = (
            Authorship.objects.filter(kind=self.kind, object_id=object_id).first() if is_valid_uuid(object_id) else None
        )
        user_id = open_identity(record.identity_cipher) if record else None
        return get_user_model().all_objects.filter(pk=user_id).first() if user_id else None

    def hide(self, object_id: Any, *, reason: str) -> None:
        self.model.objects.filter(pk=object_id).update(status=ContentStatus.HIDDEN, moderation_reason=reason[:255])

    def restore(self, object_id: Any) -> None:
        self.model.all_objects.filter(pk=object_id).update(
            status=ContentStatus.PUBLISHED, moderation_reason="", deleted_at=None
        )

    def remove(self, object_id: Any, *, reason: str) -> None:
        obj = self._get(object_id)
        if obj is not None:
            self.model.objects.filter(pk=obj.pk).update(moderation_reason=reason[:255])
            obj.delete()


class AnonymousPostAdapter(_AnonymousAdapter):
    content_type = "anonymous.post"
    label = "Anonymous post"
    kind = Authorship.Kind.POST
    model = AnonymousPost

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        post = self._get(object_id)
        return post is not None and can_view_post(viewer, post)


class AnonymousCommentAdapter(_AnonymousAdapter):
    content_type = "anonymous.comment"
    label = "Anonymous comment"
    kind = Authorship.Kind.COMMENT
    model = AnonymousComment

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        comment = self._get(object_id)
        return comment is not None and comment.status == ContentStatus.PUBLISHED and can_view_post(viewer, comment.post)
