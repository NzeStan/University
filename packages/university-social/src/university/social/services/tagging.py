"""Hashtag and mention bookkeeping shared by posts and comments."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.contrib.auth import get_user_model

from university.core.events import publish
from university.core.hooks import Hook, hooks
from university.social import events
from university.social.conf import social_settings
from university.social.models import CommentMention, Hashtag, Post, PostHashtag, PostMention
from university.social.parsing import extract_hashtags, extract_mentions
from university.social.services.common import increment


def sync_hashtags(post: Post) -> None:
    wanted = set(extract_hashtags(post.body, limit=int(social_settings.get("MAX_HASHTAGS_PER_POST", 10))))
    current = dict(PostHashtag.objects.filter(post=post).values_list("hashtag__name", "hashtag_id"))
    for name in set(current) - wanted:
        PostHashtag.objects.filter(post=post, hashtag_id=current[name]).delete()
        increment(Hashtag, current[name], "posts_count", -1)
    for name in wanted - set(current):
        tag, _ = Hashtag.objects.get_or_create(name=name)
        PostHashtag.objects.get_or_create(post=post, hashtag=tag)
        increment(Hashtag, tag.pk, "posts_count", +1)


def release_hashtags(post: Post) -> None:
    for hashtag_id in PostHashtag.objects.filter(post=post).values_list("hashtag_id", flat=True):
        increment(Hashtag, hashtag_id, "posts_count", -1)


def _mentionable(author: Any, text: str) -> list[Any]:
    handles = extract_mentions(text, limit=int(social_settings.get("MAX_MENTIONS_PER_POST", 20)))
    if not handles:
        return []
    users = get_user_model().objects.filter(handle__in=handles, status="active").exclude(pk=author.pk)
    return [u for u in users if hooks.allows(Hook.USER_CAN_INTERACT, author, u, "mention")]


def sync_post_mentions(post: Post, *, notify: bool) -> list[Any]:
    """Create mentions for newly mentioned users; return the new targets."""
    targets = _mentionable(post.author, post.body)
    existing = set(PostMention.objects.filter(post=post).values_list("user_id", flat=True))
    new = [u for u in targets if u.pk not in existing]
    PostMention.objects.bulk_create([PostMention(post=post, user=u) for u in new], ignore_conflicts=True)
    PostMention.objects.filter(post=post).exclude(user_id__in=[u.pk for u in targets]).delete()
    if notify:
        announce_mentions(post_id=post.pk, comment_id=None, author=post.author, user_ids=[u.pk for u in new])
    return new


def sync_comment_mentions(comment: Any, *, notify: bool) -> list[Any]:
    targets = _mentionable(comment.author, comment.body)
    existing = set(CommentMention.objects.filter(comment=comment).values_list("user_id", flat=True))
    new = [u for u in targets if u.pk not in existing]
    CommentMention.objects.bulk_create([CommentMention(comment=comment, user=u) for u in new], ignore_conflicts=True)
    if notify:
        announce_mentions(
            post_id=comment.post_id, comment_id=comment.pk, author=comment.author, user_ids=[u.pk for u in new]
        )
    return new


def announce_mentions(*, post_id: Any, comment_id: Any, author: Any, user_ids: Iterable[Any]) -> None:
    for user_id in user_ids:
        publish(
            events.MENTION_CREATED,
            {"post_id": post_id, "comment_id": comment_id, "author_id": author.pk, "mentioned_user_id": user_id},
            actor=author,
        )
