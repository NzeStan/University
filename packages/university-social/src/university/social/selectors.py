"""Read side of the social module — and its single source of visibility truth.

Every list (feeds, timelines, hashtags, bookmarks, comments) is built from
:func:`visible_posts`, which expresses the visibility rules as one SQL filter,
and single-object checks use :func:`can_view_post`, which applies the same
rules in Python. Tests assert both agree.

Visibility of a post for a viewer:

1. Deleted posts, posts of non-active authors and posts not ``published``
   are invisible (the author still sees their own pending/hidden posts).
2. If the viewer and the author block each other (either direction): invisible.
3. ``public``   — everyone, except: an author whose *profile* is visible to
   members only shows public posts to signed-in users, and an author whose
   profile is private shows them to followers only.
4. ``followers`` — approved followers.
5. ``private``  — the author only.
6. ``institution`` / ``campus`` / ``community`` — members of that audience
   scope, via Core's ``scopes.memberships`` hook.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q, QuerySet, Subquery

from university.core.audiences import member_scopes, member_scopes_by_type
from university.core.exceptions import NotFound
from university.permissions.scopes import Scope
from university.permissions.services import has_permission
from university.social.conf import social_settings
from university.social.constants import ContentStatus, FollowStatus, Visibility
from university.social.models import (
    Block,
    Bookmark,
    Comment,
    CommentReaction,
    Follow,
    Mute,
    Post,
    PostReaction,
    Restrict,
)

ACTIVE = "active"


def _authenticated(user: Any) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False))


# ------------------------------------------------------------ relationships
def following_ids(viewer: Any) -> QuerySet:
    return Follow.objects.filter(follower=viewer, status=FollowStatus.ACTIVE).values("followee_id")


def blocked_either_way_q(viewer: Any, field: str = "author") -> Q:
    """Q excluding rows whose ``field`` user blocks / is blocked by ``viewer``."""
    return ~Q(**{f"{field}_id__in": Block.objects.filter(blocker=viewer).values("blocked_id")}) & ~Q(
        **{f"{field}_id__in": Block.objects.filter(blocked=viewer).values("blocker_id")}
    )


def is_blocked(a: Any, b: Any) -> bool:
    """True if either user blocks the other."""
    if not (_authenticated(a) and _authenticated(b)) or a.pk == b.pk:
        return False
    return Block.objects.filter(Q(blocker=a, blocked=b) | Q(blocker=b, blocked=a)).exists()


def follows(follower: Any, followee: Any) -> bool:
    if not _authenticated(follower):
        return False
    return Follow.objects.filter(follower=follower, followee=followee, status=FollowStatus.ACTIVE).exists()


def is_moderator(user: Any, post: Post) -> bool:
    scope = Scope(post.scope_type, post.scope_id) if post.scope_type else None
    return has_permission(user, "social.content.moderate", scope)


# ------------------------------------------------------------- visibility
def audience_q(viewer: Any) -> Q:
    q = Q(pk__in=[])
    scoped = set(social_settings.get("SCOPED_VISIBILITIES", []))
    for scope_type, ids in member_scopes_by_type(viewer).items():
        if scope_type in scoped:
            q |= Q(visibility=scope_type, scope_type=scope_type, scope_id__in=ids)
    return q


def visibility_q(viewer: Any) -> Q:
    profile = "author__privacy_settings__profile_visibility"
    if not _authenticated(viewer):
        return Q(visibility=Visibility.PUBLIC) & ~Q(**{f"{profile}__in": ["members", "private"]})
    follows_author = Q(author_id__in=following_ids(viewer))
    return (
        Q(author=viewer)
        | (Q(visibility=Visibility.PUBLIC) & ~Q(**{profile: "private"}))
        | (Q(visibility__in=[Visibility.PUBLIC, Visibility.FOLLOWERS]) & follows_author)
        | audience_q(viewer)
    )


def visible_posts(viewer: Any) -> QuerySet[Post]:
    """All posts ``viewer`` may see (without feed-specific filters)."""
    qs = Post.objects.filter(author__status=ACTIVE)
    published = Q(status=ContentStatus.PUBLISHED)
    if _authenticated(viewer):
        qs = qs.filter(published | Q(author=viewer)).filter(blocked_either_way_q(viewer))
    else:
        qs = qs.filter(published)
    return qs.filter(visibility_q(viewer))


def can_view_post(viewer: Any, post: Post) -> bool:
    """Python mirror of :func:`visible_posts` for a single post."""
    author = post.author
    if post.deleted_at is not None or author.status != ACTIVE:
        return False
    authenticated = _authenticated(viewer)
    if authenticated and viewer.pk == post.author_id:
        return True
    if post.status != ContentStatus.PUBLISHED:
        return False
    if authenticated and is_blocked(viewer, author):
        return False
    privacy = getattr(author, "privacy_settings", None)
    profile_visibility = getattr(privacy, "profile_visibility", "public")
    if post.visibility == Visibility.PUBLIC:
        if not authenticated:
            return profile_visibility == "public"
        return profile_visibility != "private" or follows(viewer, author)
    if not authenticated:
        return False
    if post.visibility == Visibility.FOLLOWERS:
        return follows(viewer, author)
    if post.visibility in social_settings.get("SCOPED_VISIBILITIES", []):
        return (post.scope_type, post.scope_id) in member_scopes(viewer)
    return False


def get_visible_post(viewer: Any, post_id: Any) -> Post:
    post = Post.objects.select_related("author", "author__privacy_settings").filter(pk=post_id).first()
    if post is None or not can_view_post(viewer, post):
        raise NotFound("Post not found.")
    return post


# ------------------------------------------------------------ presentation
def with_viewer_state(qs: QuerySet[Post], viewer: Any) -> QuerySet[Post]:
    """Annotate what the viewer has done, avoiding N+1 queries in lists."""
    qs = qs.select_related("author", "repost_of", "repost_of__author", "poll").prefetch_related(
        "hashtags", "mentions__user", "media", "poll__options"
    )
    if not _authenticated(viewer):
        return qs
    return qs.annotate(
        viewer_reaction=Subquery(PostReaction.objects.filter(post=OuterRef("pk"), user=viewer).values("kind")[:1]),
        viewer_bookmarked=Exists(Bookmark.objects.filter(post=OuterRef("pk"), user=viewer)),
        viewer_reposted=Exists(
            Post.objects.filter(repost_of=OuterRef("pk"), author=viewer, body="", deleted_at__isnull=True)
        ),
    )


def visible_ids(viewer: Any, post_ids: list[Any]) -> set[Any]:
    """Which of ``post_ids`` the viewer may see (used for repost originals)."""
    if not post_ids:
        return set()
    return set(visible_posts(viewer).filter(pk__in=post_ids).values_list("pk", flat=True))


def without_muted(qs: QuerySet[Post], viewer: Any) -> QuerySet[Post]:
    if not _authenticated(viewer):
        return qs
    return qs.exclude(author_id__in=Mute.objects.filter(muter=viewer).values("muted_id"))


# ----------------------------------------------------------------- lists
def user_timeline(viewer: Any, author: Any) -> QuerySet[Post]:
    return visible_posts(viewer).filter(author=author)


def hashtag_posts(viewer: Any, tag: str) -> QuerySet[Post]:
    return without_muted(visible_posts(viewer).filter(hashtags__name=tag.lower().lstrip("#")), viewer)


def scope_posts(viewer: Any, scope_type: str, scope_id: Any) -> QuerySet[Post]:
    return without_muted(visible_posts(viewer).filter(scope_type=scope_type, scope_id=str(scope_id)), viewer)


def bookmarked_posts(viewer: Any) -> QuerySet[Post]:
    return visible_posts(viewer).filter(bookmarks__user=viewer)


def visible_comments(viewer: Any, post: Post, *, parent: Comment | None = None) -> QuerySet[Comment]:
    """Comments on a visible post, honouring blocks and restrictions."""
    qs = Comment.objects.filter(post=post, parent=parent, author__status=ACTIVE).select_related("author")
    restricted = Restrict.objects.filter(restrictor_id=post.author_id).values("restricted_id")
    if _authenticated(viewer):
        qs = qs.filter(Q(status=ContentStatus.PUBLISHED) | Q(author=viewer)).filter(blocked_either_way_q(viewer))
        if viewer.pk != post.author_id:
            qs = qs.filter(~Q(author_id__in=restricted) | Q(author=viewer))
        qs = qs.annotate(
            viewer_reaction=Subquery(
                CommentReaction.objects.filter(comment=OuterRef("pk"), user=viewer).values("kind")[:1]
            )
        )
    else:
        qs = qs.filter(status=ContentStatus.PUBLISHED).exclude(author_id__in=restricted)
    return qs.order_by("created_at", "id")


def followers_of(user: Any) -> QuerySet:
    return (
        get_user_model()
        .objects.filter(social_following__followee=user, social_following__status=FollowStatus.ACTIVE, status=ACTIVE)
        .order_by("-social_following__created_at")
    )


def following_of(user: Any) -> QuerySet:
    return (
        get_user_model()
        .objects.filter(social_followers__follower=user, social_followers__status=FollowStatus.ACTIVE, status=ACTIVE)
        .order_by("-social_followers__created_at")
    )
