"""Hook implementations connecting social to Core (registered in apps.py)."""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from university.social.constants import FollowStatus, MentionPolicy


def _auth(user: Any) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False))


def can_view_profile(viewer: Any, target: Any) -> bool | None:
    """Users who block each other cannot see each other's profiles."""
    from university.social.selectors import is_blocked

    if _auth(viewer) and is_blocked(viewer, target):
        return False
    return None


def can_interact(actor: Any, target: Any, action: str) -> bool | None:
    """Blocks stop every interaction; mention policies limit mentions."""
    from university.social.selectors import follows, is_blocked
    from university.social.services.profiles import get_social_profile

    if not (_auth(actor) and target is not None):
        return None
    if is_blocked(actor, target):
        return False
    if action == "mention":
        policy = get_social_profile(target).allow_mentions_from
        if policy == MentionPolicy.NOBODY:
            return False
        if policy == MentionPolicy.FOLLOWING and not follows(target, actor):
            return False
    return None


def public_profile(target: Any, viewer: Any) -> dict[str, Any]:
    from university.social.models import Follow
    from university.social.services.profiles import get_social_profile

    profile = get_social_profile(target)
    data: dict[str, Any] = {
        "bio": profile.bio,
        "website": profile.website,
        "followers_count": profile.followers_count,
        "following_count": profile.following_count,
        "posts_count": profile.posts_count,
        "requires_follow_approval": profile.requires_follow_approval,
    }
    if _auth(viewer) and viewer.pk != target.pk:
        relations = dict(
            Follow.objects.filter(
                Q(follower=viewer, followee=target) | Q(follower=target, followee=viewer)
            ).values_list("follower_id", "status")
        )
        data["relationship"] = {
            "following": relations.get(viewer.pk),  # "active" | "pending" | None
            "followed_by": relations.get(target.pk) == FollowStatus.ACTIVE,
        }
    return {"social": data}


def export_data(user: Any) -> dict[str, Any]:
    from university.social.models import Block, Bookmark, Comment, Follow, Mute, Post, Restrict

    return {
        "social": {
            "posts": [
                {
                    "id": p.pk,
                    "body": p.body,
                    "visibility": p.visibility,
                    "created_at": p.created_at,
                    "edited_at": p.edited_at,
                    "repost_of": p.repost_of_id,
                }
                for p in Post.objects.filter(author=user).order_by("-created_at")[:10000]
            ],
            "comments": [
                {"id": c.pk, "post": c.post_id, "body": c.body, "created_at": c.created_at}
                for c in Comment.objects.filter(author=user).order_by("-created_at")[:10000]
            ],
            "following": list(Follow.objects.filter(follower=user).values_list("followee_id", flat=True)),
            "followers": list(Follow.objects.filter(followee=user).values_list("follower_id", flat=True)),
            "blocked": list(Block.objects.filter(blocker=user).values_list("blocked_id", flat=True)),
            "muted": list(Mute.objects.filter(muter=user).values_list("muted_id", flat=True)),
            "restricted": list(Restrict.objects.filter(restrictor=user).values_list("restricted_id", flat=True)),
            "bookmarks": list(Bookmark.objects.filter(user=user).values_list("post_id", flat=True)),
        }
    }


def purge(user_id: Any) -> None:
    """Erase a purged user's social content and recompute affected counters."""
    from django.db.models import Count

    from university.social.models import (
        Comment,
        CommentReaction,
        Follow,
        Post,
        PostMedia,
        PostReaction,
        SocialProfile,
    )

    touched_posts = set(PostReaction.objects.filter(user_id=user_id).values_list("post_id", flat=True))
    touched_posts |= set(Comment.all_objects.filter(author_id=user_id).values_list("post_id", flat=True))
    touched_users = set(Follow.objects.filter(follower_id=user_id).values_list("followee_id", flat=True))
    touched_users |= set(Follow.objects.filter(followee_id=user_id).values_list("follower_id", flat=True))
    for media in PostMedia.objects.filter(owner_id=user_id):
        media.file.delete(save=False)
    PostMedia.objects.filter(owner_id=user_id).delete()
    Post.all_objects.filter(author_id=user_id).hard_delete()
    Comment.all_objects.filter(author_id=user_id).hard_delete()
    PostReaction.objects.filter(user_id=user_id).delete()
    CommentReaction.objects.filter(user_id=user_id).delete()
    SocialProfile.objects.filter(user_id=user_id).update(bio="", website="")
    from university.social.models import Block, Bookmark, Mute, Restrict

    for model, fields in (
        (Follow, ("follower", "followee")),
        (Block, ("blocker", "blocked")),
        (Mute, ("muter", "muted")),
        (Restrict, ("restrictor", "restricted")),
    ):
        model.objects.filter(Q(**{f"{fields[0]}_id": user_id}) | Q(**{f"{fields[1]}_id": user_id})).delete()
    Bookmark.objects.filter(user_id=user_id).delete()
    for post in Post.all_objects.filter(pk__in=touched_posts).annotate(
        n_reactions=Count("reactions", distinct=True), n_comments=Count("comments", distinct=True)
    ):
        Post.all_objects.filter(pk=post.pk).update(reaction_count=post.n_reactions, comment_count=post.n_comments)
    for uid in touched_users:
        SocialProfile.objects.filter(user_id=uid).update(
            followers_count=Follow.objects.filter(followee_id=uid, status=FollowStatus.ACTIVE).count(),
            following_count=Follow.objects.filter(follower_id=uid, status=FollowStatus.ACTIVE).count(),
        )
