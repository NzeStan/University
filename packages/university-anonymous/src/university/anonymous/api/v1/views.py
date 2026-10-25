from __future__ import annotations

from typing import Any

from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.anonymous import reveal, selectors, services
from university.anonymous.api.v1 import serializers as s
from university.anonymous.models import AnonymousPost, Authorship, RevealRequest
from university.core.api.pagination import CursorPagination, PageNumberPagination
from university.core.api.schema import OpenApiParameter, OpenApiTypes, extend_schema
from university.permissions.drf import require_permission


def _post_page(request: Request, posts: list[Any]) -> list[dict[str, Any]]:
    authored = selectors.authored_ids(request.user, Authorship.Kind.POST, [p.pk for p in posts])
    return s.AnonymousPostSerializer(posts, many=True, context={"authored": authored}).data


def _post_detail(request: Request, post_id: Any) -> dict[str, Any]:
    selectors.get_visible_post(request.user, post_id)  # 404 unless visible (or the viewer's own)
    post = selectors.with_viewer_state(AnonymousPost.objects.filter(pk=post_id), request.user).get()
    return _post_page(request, [post])[0]


class FeedView(APIView):
    """Posts in the viewer's audiences (optionally one audience)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="anonymous_posts_list",
        parameters=[OpenApiParameter("audience_type", str), OpenApiParameter("audience_id", str)],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request: Request) -> Response:
        qs = selectors.visible_posts(request.user)
        audience_type, audience_id = request.query_params.get("audience_type"), request.query_params.get("audience_id")
        if audience_type and audience_id:
            qs = qs.filter(scope_type=audience_type[:32], scope_id=audience_id[:64])
        paginator = CursorPagination()
        page = paginator.paginate_queryset(selectors.with_viewer_state(qs, request.user), request, view=self)
        return paginator.get_paginated_response(_post_page(request, page))

    @extend_schema(request=s.AnonymousPostCreateSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        serializer = s.AnonymousPostCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        post = services.create_post(author=request.user, **serializer.validated_data)
        return Response(_post_detail(request, post.pk), status=status.HTTP_201_CREATED)


class PostDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request: Request, post_id: Any) -> Response:
        return Response(_post_detail(request, post_id))

    @extend_schema(responses={204: None})
    def delete(self, request: Request, post_id: Any) -> Response:
        services.delete_own_post(user=request.user, post_id=post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CommentListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request: Request, post_id: Any) -> Response:
        post = selectors.get_visible_post(request.user, post_id)
        paginator = CursorPagination()
        paginator.ordering = ("position",)
        page = paginator.paginate_queryset(selectors.visible_comments(post), request, view=self)
        authored = selectors.authored_ids(request.user, Authorship.Kind.COMMENT, [c.pk for c in page])
        return paginator.get_paginated_response(
            s.AnonymousCommentSerializer(page, many=True, context={"authored": authored}).data
        )

    @extend_schema(request=s.AnonymousCommentCreateSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request, post_id: Any) -> Response:
        serializer = s.AnonymousCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = services.create_comment(author=request.user, post_id=post_id, body=serializer.validated_data["body"])
        data = s.AnonymousCommentSerializer(comment, context={"authored": {str(comment.pk)}}).data
        return Response(data, status=status.HTTP_201_CREATED)


class CommentDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, comment_id: Any) -> Response:
        services.delete_own_comment(user=request.user, comment_id=comment_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReactionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.AnonymousReactionSerializer, responses={204: None})
    def post(self, request: Request, post_id: Any) -> Response:
        serializer = s.AnonymousReactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.react(user=request.user, post_id=post_id, kind=serializer.validated_data["kind"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, post_id: Any) -> Response:
        services.unreact(user=request.user, post_id=post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class HideView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, post_id: Any) -> Response:
        services.hide_for_me(user=request.user, post_id=post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, post_id: Any) -> Response:
        services.unhide_for_me(user=request.user, post_id=post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ reveal
class RevealRequestListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, require_permission("anonymous.identity.reveal")]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        paginator = PageNumberPagination()
        qs = RevealRequest.objects.select_related("requester", "approver").order_by("-created_at")
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(s.AnonymousRevealRequestSerializer(page, many=True).data)

    @extend_schema(request=s.AnonymousRevealRequestCreateSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        serializer = s.AnonymousRevealRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reveal_request = reveal.request_reveal(requester=request.user, **serializer.validated_data)
        return Response(s.AnonymousRevealRequestSerializer(reveal_request).data, status=status.HTTP_201_CREATED)


class RevealDecisionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.AnonymousRevealDecisionSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request: Request, request_id: Any) -> Response:
        serializer = s.AnonymousRevealDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decided = reveal.decide_reveal(approver=request.user, request_id=request_id, **serializer.validated_data)
        return Response(s.AnonymousRevealRequestSerializer(decided).data)


class RevealIdentityView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request: Request, request_id: Any) -> Response:
        identity = reveal.retrieve_identity(requester=request.user, request_id=request_id)
        response = Response(identity)
        response["Cache-Control"] = "no-store"
        return response
