from __future__ import annotations

from collections import defaultdict
from typing import Any

from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.pagination import CursorPagination, PageNumberPagination
from university.core.api.schema import OpenApiParameter, OpenApiTypes, extend_schema
from university.core.exceptions import AuthenticationFailed, NotFound, ValidationError
from university.core.ids import is_valid_uuid
from university.social import selectors, services
from university.social.api.v1 import serializers as s
from university.social.conf import social_settings
from university.social.constants import FollowStatus
from university.social.feeds import get_feed
from university.social.models import Block, Follow, Mute, PollVote, Restrict
from university.users.selectors import get_visible_user


# ------------------------------------------------------------------ helpers
def post_context(request: Request, posts: list[Any]) -> dict[str, Any]:
    """Per-page context computed in O(1) queries (no N+1)."""
    viewer = request.user
    originals = [p.repost_of_id for p in posts if p.repost_of_id]
    poll_votes: dict[Any, set[Any]] = defaultdict(set)
    poll_ids = [p.poll.pk for p in posts if _has_poll(p)]
    if poll_ids and viewer.is_authenticated:
        for poll_id, option_id in PollVote.objects.filter(poll_id__in=poll_ids, user=viewer).values_list(
            "poll_id", "option_id"
        ):
            poll_votes[poll_id].add(option_id)
    return {
        "request": request,
        "visible_originals": selectors.visible_ids(viewer, originals),
        "poll_votes": poll_votes,
    }


def _has_poll(post: Any) -> bool:
    try:
        return post.poll is not None
    except Exception:
        return False


def render_post(request: Request, post_id: Any) -> dict[str, Any]:
    post = selectors.with_viewer_state(selectors.visible_posts(request.user), request.user).get(pk=post_id)
    return s.PostSerializer(post, context=post_context(request, [post])).data


class PostPageView(APIView):
    """Base for cursor-paginated post lists."""

    permission_classes = [permissions.AllowAny]

    def get_posts(self, request: Request, **kwargs: Any) -> Any:
        raise NotImplementedError

    @extend_schema(parameters=[OpenApiParameter("cursor", str)], responses=OpenApiTypes.OBJECT)
    def get(self, request: Request, **kwargs: Any) -> Response:
        queryset = selectors.with_viewer_state(self.get_posts(request, **kwargs), request.user)
        paginator = CursorPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            s.PostSerializer(page, many=True, context=post_context(request, page)).data
        )


def _uuid_or_404(value: Any) -> Any:
    if not is_valid_uuid(value):
        raise NotFound()
    return value


# -------------------------------------------------------------------- posts
class PostCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.PostCreateSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        serializer = s.PostCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        post = services.create_post(
            author=request.user,
            body=data.get("body", ""),
            visibility=data.get("visibility"),
            scope_id=data.get("audience_id"),
            media=data.get("media"),
            poll=data.get("poll"),
            location=data.get("location", ""),
            comments_enabled=data.get("comments_enabled", True),
        )
        return Response(render_post(request, post.pk), status=status.HTTP_201_CREATED)


class PostDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request: Request, post_id: Any) -> Response:
        selectors.get_visible_post(request.user, post_id)
        return Response(render_post(request, post_id))

    @extend_schema(request=s.PostUpdateSerializer, responses=OpenApiTypes.OBJECT)
    def patch(self, request: Request, post_id: Any) -> Response:
        if not request.user.is_authenticated:
            raise AuthenticationFailed()
        serializer = s.PostUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.edit_post(actor=request.user, post_id=post_id, data=serializer.validated_data)
        return Response(render_post(request, post_id))

    @extend_schema(responses={204: None})
    def delete(self, request: Request, post_id: Any) -> Response:
        if not request.user.is_authenticated:
            raise AuthenticationFailed()
        services.delete_post(actor=request.user, post_id=post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class FeedView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("offset", int), OpenApiParameter("limit", int)], responses=OpenApiTypes.OBJECT
    )
    def get(self, request: Request, name: str) -> Response:
        feed = get_feed(name)
        if feed.requires_auth and not request.user.is_authenticated:
            raise AuthenticationFailed("Sign in to see this feed.", code="not_authenticated")
        if feed.cursor_paginated:
            queryset = selectors.with_viewer_state(feed.get_queryset(request.user, request.query_params), request.user)
            paginator = CursorPagination()
            page = paginator.paginate_queryset(queryset, request, view=self)
            data = s.PostSerializer(page, many=True, context=post_context(request, page)).data
            return paginator.get_paginated_response(data)
        try:
            offset = max(0, int(request.query_params.get("offset", 0)))
            limit = min(max(1, int(request.query_params.get("limit", 20))), 50)
        except ValueError:
            raise ValidationError(details={"offset": ["Must be an integer."]}) from None
        items = feed.get_items(request.user, request.query_params, offset=offset, limit=limit)
        ids = [p.pk for p in items]
        annotated = {
            p.pk: p
            for p in selectors.with_viewer_state(selectors.visible_posts(request.user).filter(pk__in=ids), request.user)
        }
        page = [annotated[i] for i in ids if i in annotated]
        data = s.PostSerializer(page, many=True, context=post_context(request, page)).data
        return Response({"offset": offset, "limit": limit, "results": data})


class UserPostsView(PostPageView):
    def get_posts(self, request: Request, user_id: Any) -> Any:
        author = get_visible_user(viewer=request.user, user_id=user_id)
        return selectors.user_timeline(request.user, author)


class HashtagPostsView(PostPageView):
    def get_posts(self, request: Request, tag: str) -> Any:
        return selectors.hashtag_posts(request.user, tag[:64])


class AudiencePostsView(PostPageView):
    def get_posts(self, request: Request, scope_type: str, scope_id: str) -> Any:
        if scope_type not in social_settings.get("SCOPED_VISIBILITIES", []):
            raise NotFound()
        return selectors.scope_posts(request.user, scope_type, scope_id[:64])


class BookmarksView(PostPageView):
    permission_classes = [permissions.IsAuthenticated]

    def get_posts(self, request: Request) -> Any:
        return selectors.bookmarked_posts(request.user)


class HashtagSearchView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(parameters=[OpenApiParameter("q", str)], responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        from university.social.models import Hashtag

        term = (request.query_params.get("q") or "").lstrip("#").lower()[:64]
        qs = Hashtag.objects.filter(posts_count__gt=0)
        if term:
            qs = qs.filter(name__startswith=term)
        return Response([{"name": h.name, "posts_count": h.posts_count} for h in qs.order_by("-posts_count")[:20]])


# -------------------------------------------------------------- interactions
class PostReactionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.ReactionSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request: Request, post_id: Any) -> Response:
        serializer = s.ReactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.react_to_post(user=request.user, post_id=post_id, kind=serializer.validated_data["kind"])
        return Response(render_post(request, post_id))

    @extend_schema(responses={204: None})
    def delete(self, request: Request, post_id: Any) -> Response:
        services.remove_post_reaction(user=request.user, post_id=_uuid_or_404(post_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class RepostView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.RepostSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request, post_id: Any) -> Response:
        serializer = s.RepostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        post = services.repost(actor=request.user, post_id=post_id, body=serializer.validated_data["body"])
        return Response(render_post(request, post.pk), status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, post_id: Any) -> Response:
        services.undo_repost(actor=request.user, post_id=post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BookmarkView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, post_id: Any) -> Response:
        services.bookmark_post(user=request.user, post_id=post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, post_id: Any) -> Response:
        services.remove_bookmark(user=request.user, post_id=post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PollVoteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.PollVoteSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request: Request, post_id: Any) -> Response:
        serializer = s.PollVoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.vote_in_poll(user=request.user, post_id=post_id, option_ids=serializer.validated_data["options"])
        return Response(render_post(request, post_id))


# ------------------------------------------------------------------ comments
class CommentListCreateView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(parameters=[OpenApiParameter("parent", str)], responses=s.CommentSerializer(many=True))
    def get(self, request: Request, post_id: Any) -> Response:
        post = selectors.get_visible_post(request.user, post_id)
        parent = None
        parent_id = request.query_params.get("parent")
        if parent_id:
            from university.social.models import Comment

            parent = Comment.objects.filter(pk=_uuid_or_404(parent_id), post=post).first()
            if parent is None:
                raise NotFound("Comment not found.")
        paginator = CursorPagination()
        paginator.ordering = ("created_at", "id")
        page = paginator.paginate_queryset(
            selectors.visible_comments(request.user, post, parent=parent), request, view=self
        )
        return paginator.get_paginated_response(s.CommentSerializer(page, many=True).data)

    @extend_schema(request=s.CommentCreateSerializer, responses={201: s.CommentSerializer})
    def post(self, request: Request, post_id: Any) -> Response:
        if not request.user.is_authenticated:
            raise AuthenticationFailed()
        serializer = s.CommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = services.create_comment(
            author=request.user,
            post_id=post_id,
            body=serializer.validated_data["body"],
            parent_id=serializer.validated_data.get("parent"),
        )
        return Response(s.CommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class CommentDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CommentUpdateSerializer, responses=s.CommentSerializer)
    def patch(self, request: Request, comment_id: Any) -> Response:
        serializer = s.CommentUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = services.edit_comment(
            actor=request.user, comment_id=comment_id, body=serializer.validated_data["body"]
        )
        return Response(s.CommentSerializer(comment).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, comment_id: Any) -> Response:
        services.delete_comment(actor=request.user, comment_id=comment_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CommentReactionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.ReactionSerializer, responses={204: None})
    def post(self, request: Request, comment_id: Any) -> Response:
        serializer = s.ReactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.react_to_comment(user=request.user, comment_id=comment_id, kind=serializer.validated_data["kind"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, comment_id: Any) -> Response:
        services.remove_comment_reaction(user=request.user, comment_id=_uuid_or_404(comment_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------- media
class MediaUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=s.MediaUploadSerializer, responses={201: s.MediaSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.MediaUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        media = services.upload_media(owner=request.user, **serializer.validated_data)
        return Response(s.MediaSerializer(media, context={"request": request}).data, status=status.HTTP_201_CREATED)


class MediaDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, media_id: Any) -> Response:
        services.delete_media(owner=request.user, media_id=media_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------- graph
class FollowView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses=s.FollowResultSerializer)
    def post(self, request: Request, user_id: Any) -> Response:
        follow = services.follow_user(follower=request.user, followee_id=user_id)
        return Response({"status": follow.status})

    @extend_schema(responses={204: None})
    def delete(self, request: Request, user_id: Any) -> Response:
        services.unfollow_user(follower=request.user, followee_id=user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class _UserListView(APIView):
    permission_classes = [permissions.AllowAny]
    direction = "followers"

    @extend_schema(responses=s.UserSummarySerializer(many=True))
    def get(self, request: Request, user_id: Any) -> Response:
        target = get_visible_user(viewer=request.user, user_id=user_id)
        profile = services.get_social_profile(target)
        is_self = request.user.is_authenticated and request.user.pk == target.pk
        if profile.requires_follow_approval and not is_self and not selectors.follows(request.user, target):
            raise NotFound("User not found.")
        qs = selectors.followers_of(target) if self.direction == "followers" else selectors.following_of(target)
        if request.user.is_authenticated:
            qs = qs.exclude(pk__in=Block.objects.filter(blocker=request.user).values("blocked_id"))
            qs = qs.exclude(pk__in=Block.objects.filter(blocked=request.user).values("blocker_id"))
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(s.UserSummarySerializer(page, many=True).data)


class FollowersView(_UserListView):
    direction = "followers"


class FollowingView(_UserListView):
    direction = "following"


class FollowRequestsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.FollowSerializer(many=True))
    def get(self, request: Request) -> Response:
        qs = Follow.objects.filter(followee=request.user, status=FollowStatus.PENDING).select_related("follower")
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs.order_by("-created_at"), request, view=self)
        return paginator.get_paginated_response(s.FollowSerializer(page, many=True, context={"side": "follower"}).data)


class FollowRequestActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    approve = True

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, follow_id: Any) -> Response:
        if self.approve:
            services.approve_follow_request(user=request.user, follow_id=follow_id)
        else:
            services.decline_follow_request(user=request.user, follow_id=follow_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RemoveFollowerView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, user_id: Any) -> Response:
        services.remove_follower(user=request.user, follower_id=user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class _EdgeView(APIView):
    """Block / mute / restrict a user (idempotent)."""

    permission_classes = [permissions.IsAuthenticated]
    kind = "block"

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, user_id: Any) -> Response:
        action = {"block": services.block_user, "mute": services.mute_user, "restrict": services.restrict_user}
        kwarg = {"block": "blocker", "mute": "muter", "restrict": "restrictor"}[self.kind]
        action[self.kind](**{kwarg: request.user, "target_id": user_id})
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, user_id: Any) -> Response:
        action = {"block": services.unblock_user, "mute": services.unmute_user, "restrict": services.unrestrict_user}
        kwarg = {"block": "blocker", "mute": "muter", "restrict": "restrictor"}[self.kind]
        action[self.kind](**{kwarg: request.user, "target_id": _uuid_or_404(user_id)})
        return Response(status=status.HTTP_204_NO_CONTENT)


class BlockView(_EdgeView):
    kind = "block"


class MuteView(_EdgeView):
    kind = "mute"


class RestrictView(_EdgeView):
    kind = "restrict"


class _MyEdgesView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    model: Any = Block
    owner_field = "blocker"
    target_field = "blocked"

    @extend_schema(responses=s.UserSummarySerializer(many=True))
    def get(self, request: Request) -> Response:
        qs = self.model.objects.filter(**{self.owner_field: request.user}).select_related(self.target_field)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs.order_by("-created_at"), request, view=self)
        users = [getattr(edge, self.target_field) for edge in page]
        return paginator.get_paginated_response(s.UserSummarySerializer(users, many=True).data)


class MyBlocksView(_MyEdgesView):
    model, owner_field, target_field = Block, "blocker", "blocked"


class MyMutesView(_MyEdgesView):
    model, owner_field, target_field = Mute, "muter", "muted"


class MyRestrictionsView(_MyEdgesView):
    model, owner_field, target_field = Restrict, "restrictor", "restricted"


class MyProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.SocialProfileSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.SocialProfileSerializer(services.get_social_profile(request.user)).data)

    @extend_schema(request=s.SocialProfileSerializer, responses=s.SocialProfileSerializer)
    def patch(self, request: Request) -> Response:
        profile = services.get_social_profile(request.user)
        serializer = s.SocialProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profile = services.update_social_profile(request.user, serializer.validated_data)
        return Response(s.SocialProfileSerializer(profile).data)


# ---------------------------------------------------------------- moderation
class ModerationView(APIView):
    """Hide or restore content (authorised in the services)."""

    permission_classes = [permissions.IsAuthenticated]
    target = "post"
    action_name = "hide"

    @extend_schema(request=s.ModerationSerializer, responses={204: None})
    def post(self, request: Request, object_id: Any) -> Response:
        serializer = s.ModerationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data["reason"]
        handlers = {
            ("post", "hide"): lambda: services.hide_post(actor=request.user, post_id=object_id, reason=reason),
            ("post", "restore"): lambda: services.restore_post(actor=request.user, post_id=object_id, reason=reason),
            ("comment", "hide"): lambda: services.hide_comment(actor=request.user, comment_id=object_id, reason=reason),
            ("comment", "restore"): lambda: services.restore_comment(
                actor=request.user, comment_id=object_id, reason=reason
            ),
        }
        handlers[(self.target, self.action_name)]()
        return Response(status=status.HTTP_204_NO_CONTENT)


def moderation_view(target: str, action_name: str) -> type[ModerationView]:
    return type(
        f"{target.title()}{action_name.title()}View", (ModerationView,), {"target": target, "action_name": action_name}
    )
