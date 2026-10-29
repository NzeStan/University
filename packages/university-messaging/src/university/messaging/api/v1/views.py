from __future__ import annotations

from typing import Any

from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.pagination import CursorPagination, PageNumberPagination
from university.core.api.schema import OpenApiParameter, extend_schema, paginated
from university.messaging import selectors, services
from university.messaging.api.v1 import serializers as s
from university.messaging.models import Participant


class MessagePagination(CursorPagination):
    ordering = ("-created_at", "-id")


def _conversation(request: Request, participant: Participant) -> dict[str, Any]:
    annotated = selectors.participations(request.user, "inbox").filter(pk=participant.pk).first() or next(
        (
            p
            for f in ("requests", "archived")
            for p in selectors.participations(request.user, f).filter(pk=participant.pk)
        ),
        participant,
    )
    return s.MessagingConversationSerializer(annotated, context={"viewer": request.user}).data


class ConversationListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("folder", str, description="inbox (default), requests or archived")],
        responses=paginated(s.MessagingConversationSerializer),
    )
    def get(self, request: Request) -> Response:
        qs = selectors.participations(request.user, request.query_params.get("folder", "inbox"))
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        context = {"viewer": request.user}
        return paginator.get_paginated_response(
            s.MessagingConversationSerializer(page, many=True, context=context).data
        )

    @extend_schema(request=s.MessagingStartSerializer, responses={201: s.MessagingConversationSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.MessagingStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation, _ = services.start_conversation(sender=request.user, **serializer.validated_data)
        participant = services.membership(request.user, conversation.pk)
        return Response(_conversation(request, participant), status=status.HTTP_201_CREATED)


class ConversationDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.MessagingConversationSerializer)
    def get(self, request: Request, conversation_id: Any) -> Response:
        return Response(_conversation(request, services.membership(request.user, conversation_id)))

    @extend_schema(request=s.MessagingConversationUpdateSerializer, responses=s.MessagingConversationSerializer)
    def patch(self, request: Request, conversation_id: Any) -> Response:
        serializer = s.MessagingConversationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "title" in data:
            services.rename(user=request.user, conversation_id=conversation_id, title=data["title"])
        participant = services.update_participation(
            user=request.user, conversation_id=conversation_id, muted=data.get("muted"), archived=data.get("archived")
        )
        return Response(_conversation(request, participant))


class _RequestResponseView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    accept = True

    @extend_schema(request=None, responses=s.MessagingConversationSerializer)
    def post(self, request: Request, conversation_id: Any) -> Response:
        participant = services.respond_to_request(
            user=request.user, conversation_id=conversation_id, accept=self.accept
        )
        return Response(s.MessagingConversationSerializer(participant, context={"viewer": request.user}).data)


class AcceptView(_RequestResponseView):
    accept = True


class DeclineView(_RequestResponseView):
    accept = False


class ReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, conversation_id: Any) -> Response:
        services.mark_read(user=request.user, conversation_id=conversation_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LeaveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, conversation_id: Any) -> Response:
        services.leave(user=request.user, conversation_id=conversation_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ParticipantsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.MessagingAddParticipantsSerializer, responses=s.MessagingConversationSerializer)
    def post(self, request: Request, conversation_id: Any) -> Response:
        serializer = s.MessagingAddParticipantsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_participants(user=request.user, conversation_id=conversation_id, **serializer.validated_data)
        return Response(_conversation(request, services.membership(request.user, conversation_id)))


class MessageListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @property
    def throttle_scope(self) -> str | None:  # type: ignore[override]
        return "messaging_send" if self.request.method == "POST" else None

    @extend_schema(
        parameters=[OpenApiParameter("cursor", str)], responses=paginated(s.MessagingMessageSerializer, style="cursor")
    )
    def get(self, request: Request, conversation_id: Any) -> Response:
        services.membership(request.user, conversation_id)
        paginator = MessagePagination()
        page = paginator.paginate_queryset(selectors.messages(conversation_id), request, view=self)
        data = s.MessagingMessageSerializer(page, many=True, context={"viewer": request.user}).data
        return paginator.get_paginated_response(data)

    @extend_schema(request=s.MessagingSendSerializer, responses={201: s.MessagingMessageSerializer})
    def post(self, request: Request, conversation_id: Any) -> Response:
        serializer = s.MessagingSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = services.send_message(
            sender=request.user, conversation_id=conversation_id, **serializer.validated_data
        )
        data = s.MessagingMessageSerializer(message, context={"viewer": request.user}).data
        return Response(data, status=status.HTTP_201_CREATED)


class MessageDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.MessagingEditSerializer, responses=s.MessagingMessageSerializer)
    def patch(self, request: Request, message_id: Any) -> Response:
        serializer = s.MessagingEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = services.edit_message(
            user=request.user, message_id=message_id, body=serializer.validated_data["body"]
        )
        return Response(s.MessagingMessageSerializer(message, context={"viewer": request.user}).data)

    @extend_schema(responses=s.MessagingMessageSerializer)
    def delete(self, request: Request, message_id: Any) -> Response:
        message = services.delete_message(user=request.user, message_id=message_id)
        return Response(s.MessagingMessageSerializer(message, context={"viewer": request.user}).data)


class UnreadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.MessagingUnreadSerializer)
    def get(self, request: Request) -> Response:
        return Response(selectors.unread_totals(request.user))


class SettingsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.MessagingSettingsSerializer)
    def get(self, request: Request) -> Response:
        return Response({"allow_requests": services.settings_for(request.user).allow_requests})

    @extend_schema(request=s.MessagingSettingsSerializer, responses=s.MessagingSettingsSerializer)
    def patch(self, request: Request) -> Response:
        serializer = s.MessagingSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = services.update_settings(request.user, **serializer.validated_data)
        return Response({"allow_requests": updated.allow_requests})
