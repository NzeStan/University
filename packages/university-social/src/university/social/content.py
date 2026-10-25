"""Content adapters exposing social posts and comments to cross-cutting modules.

Moderation (or search, analytics …) acts on social content through these
without importing social, and social never imports them.
"""

from __future__ import annotations

from typing import Any

from university.core.content import ContentAdapter, ContentRef
from university.core.events import publish
from university.core.ids import is_valid_uuid
from university.social import events
from university.social.constants import ContentStatus
from university.social.models import Comment, Post

EXCERPT_LENGTH = 500


def _scope(post: Post) -> tuple[str, str] | None:
    return (post.scope_type, post.scope_id) if post.scope_type else None


class SocialPostAdapter(ContentAdapter):
    content_type = "social.post"
    moderatable = True
    label = "Post"

    def iter_ids(self) -> Any:
        """Live items, for search backfills."""
        from university.social.models import Post

        return (str(pk) for pk in Post.objects.filter(status="published").values_list("pk", flat=True).iterator())

    def _get(self, object_id: Any) -> Post | None:
        if not is_valid_uuid(object_id):
            return None
        return Post.objects.select_related("author").filter(pk=object_id).first()

    def resolve(self, object_id: Any) -> ContentRef | None:
        post = self._get(object_id)
        if post is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(post.pk),
            author_id=str(post.author_id),
            scope=_scope(post),
            excerpt=post.body[:EXCERPT_LENGTH],
            status=post.status,
            created_at=post.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        from university.social.selectors import can_view_post

        post = self._get(object_id)
        return post is not None and can_view_post(viewer, post)

    def hide(self, object_id: Any, *, reason: str) -> None:
        post = self._get(object_id)
        if post is None:
            return
        Post.objects.filter(pk=post.pk).update(status=ContentStatus.HIDDEN, moderation_reason=reason[:255])
        publish(events.POST_HIDDEN, {"post_id": post.pk, "author_id": post.author_id})

    def restore(self, object_id: Any) -> None:
        from university.social.services.posts import publish_post_side_effects

        post = Post.all_objects.select_related("author").filter(pk=object_id).first()
        if post is None:
            return
        was_pending = post.status == ContentStatus.PENDING_REVIEW
        if post.deleted_at is not None:
            post.restore()
        Post.all_objects.filter(pk=post.pk).update(status=ContentStatus.PUBLISHED, moderation_reason="")
        post.status = ContentStatus.PUBLISHED
        if was_pending:
            publish_post_side_effects(post)
        else:
            publish(events.POST_RESTORED, {"post_id": post.pk, "author_id": post.author_id})

    def remove(self, object_id: Any, *, reason: str) -> None:
        from university.social.services.posts import remove_post_records

        post = self._get(object_id)
        if post is not None:
            Post.objects.filter(pk=post.pk).update(moderation_reason=reason[:255])
            remove_post_records(post)
            publish(events.POST_DELETED, {"post_id": post.pk, "author_id": post.author_id})


class SocialCommentAdapter(ContentAdapter):
    content_type = "social.comment"
    moderatable = True
    label = "Comment"

    def iter_ids(self) -> Any:
        """Live items, for search backfills."""
        from university.social.models import Comment

        return (str(pk) for pk in Comment.objects.filter(status="published").values_list("pk", flat=True).iterator())

    def _get(self, object_id: Any) -> Comment | None:
        if not is_valid_uuid(object_id):
            return None
        return Comment.objects.select_related("post", "author").filter(pk=object_id).first()

    def resolve(self, object_id: Any) -> ContentRef | None:
        comment = self._get(object_id)
        if comment is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(comment.pk),
            author_id=str(comment.author_id),
            scope=_scope(comment.post),
            excerpt=comment.body[:EXCERPT_LENGTH],
            status=comment.status,
            created_at=comment.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        from university.social.selectors import visible_comments

        comment = self._get(object_id)
        if comment is None or not SocialPostAdapter().can_view(viewer, comment.post_id):
            return False
        parent = Comment.objects.filter(pk=comment.parent_id).first() if comment.parent_id else None
        return visible_comments(viewer, comment.post, parent=parent).filter(pk=comment.pk).exists()

    def hide(self, object_id: Any, *, reason: str) -> None:
        comment = self._get(object_id)
        if comment is not None:
            Comment.objects.filter(pk=comment.pk).update(status=ContentStatus.HIDDEN, moderation_reason=reason[:255])
            publish(events.COMMENT_HIDDEN, {"comment_id": comment.pk, "author_id": comment.author_id})

    def restore(self, object_id: Any) -> None:
        comment = Comment.all_objects.filter(pk=object_id).first()
        if comment is None:
            return
        if comment.deleted_at is not None:
            comment.restore()
        Comment.all_objects.filter(pk=comment.pk).update(status=ContentStatus.PUBLISHED, moderation_reason="")

    def remove(self, object_id: Any, *, reason: str) -> None:
        from university.social.services.comments import remove_comment_records

        comment = self._get(object_id)
        if comment is not None:
            remove_comment_records(comment)
            publish(events.COMMENT_DELETED, {"comment_id": comment.pk, "author_id": comment.author_id})
