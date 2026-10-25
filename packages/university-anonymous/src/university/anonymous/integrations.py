"""Privacy hooks for anonymous content.

There is deliberately no index from users to their anonymous items, so data
export and purge *scan* the authorship records and test each owner token for
the user. This costs one HMAC per item (≈1 µs) and runs only on rare,
throttled operations — the price of having no author index to leak.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from university.anonymous.identity import owner_token
from university.anonymous.models import AnonymousComment, AnonymousPost, AnonymousReaction, Authorship, HiddenPost
from university.core.crypto import constant_time_equals

CHUNK = 5000


def _owned_records(user_id: Any) -> Iterator[Authorship]:
    for record in Authorship.objects.all().iterator(chunk_size=CHUNK):
        if constant_time_equals(owner_token(record.kind, record.object_id, user_id), record.owner_token):
            yield record


def export_data(user: Any) -> dict[str, Any]:
    posts, comments = [], []
    for record in _owned_records(user.pk):
        if record.kind == Authorship.Kind.POST:
            post = AnonymousPost.objects.filter(pk=record.object_id).first()
            if post:
                posts.append(
                    {"id": post.pk, "body": post.body, "visibility": post.visibility, "created_at": post.created_at}
                )
        else:
            comment = AnonymousComment.objects.filter(pk=record.object_id).first()
            if comment:
                comments.append(
                    {"id": comment.pk, "post": comment.post_id, "body": comment.body, "created_at": comment.created_at}
                )
    return {"anonymous": {"posts": posts, "comments": comments}}


def purge(user_id: Any) -> None:
    """Hard-delete a purged user's anonymous content and its authorship records."""
    for record in list(_owned_records(user_id)):
        if record.kind == Authorship.Kind.POST:
            AnonymousPost.all_objects.filter(pk=record.object_id).hard_delete()
        else:
            AnonymousComment.all_objects.filter(pk=record.object_id).hard_delete()
        record.delete()
    AnonymousReaction.objects.filter(user_id=user_id).delete()
    HiddenPost.objects.filter(user_id=user_id).delete()
