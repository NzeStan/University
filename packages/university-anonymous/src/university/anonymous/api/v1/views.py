from __future__ import annotations

from typing import Any

from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.anonymous import inbox, reveal, selectors, services
from university.anonymous.api.v1 import serializers as s
from university.anonymous.models import AnonymousMessage, AnonymousPost, Authorship, RevealRequest
from university.core.api.pagination import CursorPagination, PageNumberPagination
from university.core.api.schema import OpenApiParameter, extend_schema, paginated
from university.core.api.serializers import DetailSerializer
from university.permissions.drf import require_permission
from university.users.refs import person_ref
from university.users.selectors import get_visible_user


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
        parameters=[
            OpenApiParameter("audience_type", str),
            OpenApiParameter("audience_id", str),
            OpenApiParameter("cursor", str),
        ],
        responses=paginated(s.AnonymousPostSerializer, style="cursor"),
    )
    def get(self, request: Request) -> Response:
        qs = selectors.visible_posts(request.user)
        audience_type, audience_id = request.query_params.get("audience_type"), request.query_params.get("audience_id")
        if audience_type and audience_id:
            qs = qs.filter(scope_type=audience_type[:32], scope_id=audience_id[:64])
        paginator = CursorPagination()
        page = paginator.paginate_queryset(selectors.with_viewer_state(qs, request.user), request, view=self)
        return paginator.get_paginated_response(_post_page(request, page))

    @extend_schema(request=s.AnonymousPostCreateSerializer, responses={201: s.AnonymousPostSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.AnonymousPostCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        post = services.create_post(author=request.user, **serializer.validated_data)
        return Response(_post_detail(request, post.pk), status=status.HTTP_201_CREATED)


class PostDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.AnonymousPostSerializer)
    def get(self, request: Request, post_id: Any) -> Response:
        return Response(_post_detail(request, post_id))

    @extend_schema(responses={204: None})
    def delete(self, request: Request, post_id: Any) -> Response:
        services.delete_own_post(user=request.user, post_id=post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CommentListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=paginated(s.AnonymousCommentSerializer, style="cursor"))
    def get(self, request: Request, post_id: Any) -> Response:
        post = selectors.get_visible_post(request.user, post_id)
        paginator = CursorPagination()
        paginator.ordering = ("position",)
        page = paginator.paginate_queryset(selectors.visible_comments(post), request, view=self)
        authored = selectors.authored_ids(request.user, Authorship.Kind.COMMENT, [c.pk for c in page])
        return paginator.get_paginated_response(
            s.AnonymousCommentSerializer(page, many=True, context={"authored": authored}).data
        )

    @extend_schema(request=s.AnonymousCommentCreateSerializer, responses={201: s.AnonymousCommentSerializer})
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

    @extend_schema(responses=paginated(s.AnonymousRevealRequestSerializer))
    def get(self, request: Request) -> Response:
        paginator = PageNumberPagination()
        qs = RevealRequest.objects.select_related("requester", "approver").order_by("-created_at")
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(s.AnonymousRevealRequestSerializer(page, many=True).data)

    @extend_schema(
        request=s.AnonymousRevealRequestCreateSerializer, responses={201: s.AnonymousRevealRequestSerializer}
    )
    def post(self, request: Request) -> Response:
        serializer = s.AnonymousRevealRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reveal_request = reveal.request_reveal(requester=request.user, **serializer.validated_data)
        return Response(s.AnonymousRevealRequestSerializer(reveal_request).data, status=status.HTTP_201_CREATED)


class RevealDecisionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.AnonymousRevealDecisionSerializer, responses=s.AnonymousRevealRequestSerializer)
    def post(self, request: Request, request_id: Any) -> Response:
        serializer = s.AnonymousRevealDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decided = reveal.decide_reveal(approver=request.user, request_id=request_id, **serializer.validated_data)
        return Response(s.AnonymousRevealRequestSerializer(decided).data)


class RevealIdentityView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.AnonymousRevealedIdentitySerializer)
    def get(self, request: Request, request_id: Any) -> Response:
        identity = reveal.retrieve_identity(requester=request.user, request_id=request_id)
        response = Response(identity)
        response["Cache-Control"] = "no-store"
        return response


# ------------------------------------------------------------------ anonymous inbox
def _inbox_data(user: Any) -> dict[str, Any]:
    box = inbox.get_inbox(user)
    return {
        "enabled": box.enabled,
        "prompt": box.prompt,
        "unread_count": box.messages.filter(read_at__isnull=True, status="published").count(),
        "blocked_senders": box.blocked_senders.count(),
    }


class MyInboxView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.AnonymousInboxSerializer)
    def get(self, request: Request) -> Response:
        return Response(_inbox_data(request.user))

    @extend_schema(request=s.AnonymousInboxUpdateSerializer, responses=s.AnonymousInboxSerializer)
    def patch(self, request: Request) -> Response:
        serializer = s.AnonymousInboxUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inbox.update_inbox(request.user, **serializer.validated_data)
        return Response(_inbox_data(request.user))


class MyInboxMessagesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("unanswered", bool)], responses=paginated(s.AnonymousInboxMessageSerializer)
    )
    def get(self, request: Request) -> Response:
        qs = AnonymousMessage.objects.filter(inbox=inbox.get_inbox(request.user), status="published")
        if str(request.query_params.get("unanswered", "")).lower() in ("1", "true"):
            qs = qs.filter(answered_at__isnull=True)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs.order_by("-created_at"), request, view=self)
        return paginator.get_paginated_response(s.AnonymousInboxMessageSerializer(page, many=True).data)


class MyInboxMessageView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, message_id: Any) -> Response:
        inbox.delete_message(owner=request.user, message_id=message_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyInboxMessageReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses=s.AnonymousInboxMessageSerializer)
    def post(self, request: Request, message_id: Any) -> Response:
        message = inbox.mark_read(owner=request.user, message_id=message_id)
        return Response(s.AnonymousInboxMessageSerializer(message).data)


class MyInboxAnswerView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.AnonymousAnswerSerializer, responses=s.AnonymousInboxMessageSerializer)
    def post(self, request: Request, message_id: Any) -> Response:
        serializer = s.AnonymousAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = inbox.answer(
            owner=request.user,
            message_id=message_id,
            text=serializer.validated_data["answer"],
            public=serializer.validated_data["public"],
        )
        return Response(s.AnonymousInboxMessageSerializer(message).data)

    @extend_schema(request=None, responses=s.AnonymousInboxMessageSerializer, description="Make the answer private.")
    def delete(self, request: Request, message_id: Any) -> Response:
        message = inbox.unpublish_answer(owner=request.user, message_id=message_id)
        return Response(s.AnonymousInboxMessageSerializer(message).data)


class MyInboxBlockSenderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={204: None}, description="Block whoever sent this, without learning who.")
    def post(self, request: Request, message_id: Any) -> Response:
        inbox.block_sender(owner=request.user, message_id=message_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublicInboxView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.AnonymousPublicInboxSerializer)
    def get(self, request: Request, handle: str) -> Response:
        owner = get_visible_user(viewer=request.user, handle=handle)
        box = inbox.open_inbox_for(owner)
        answers = box.messages.filter(status="published", answer_public=True).count()
        return Response({"owner": person_ref(owner), "prompt": box.prompt, "answers_count": answers})


class SendMessageView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.AnonymousMessageSendSerializer, responses={202: DetailSerializer})
    def post(self, request: Request, handle: str) -> Response:
        serializer = s.AnonymousMessageSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        owner = get_visible_user(viewer=request.user, handle=handle)
        inbox.send_message(sender=request.user, owner=owner, body=serializer.validated_data["body"])
        return Response({"detail": "Sent anonymously."}, status=status.HTTP_202_ACCEPTED)


class PublicAnswersView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=paginated(s.AnonymousPublicAnswerSerializer))
    def get(self, request: Request, handle: str) -> Response:
        owner = get_visible_user(viewer=request.user, handle=handle)
        box = inbox.open_inbox_for(owner)
        qs = box.messages.filter(status="published", answer_public=True).order_by("-answered_at")
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(s.AnonymousPublicAnswerSerializer(page, many=True).data)
