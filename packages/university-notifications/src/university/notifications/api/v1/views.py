from __future__ import annotations

from typing import Any

from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.pagination import CursorPagination
from university.core.api.schema import OpenApiParameter, extend_schema, paginated
from university.notifications import selectors, services
from university.notifications.api.v1 import serializers as s
from university.notifications.channels import enabled_channels
from university.notifications.constants import Channel
from university.notifications.preferences import categories, channel_mode


class FeedPagination(CursorPagination):
    ordering = ("-last_activity_at", "-id")


def _item(request: Request, notification: Any) -> dict[str, Any]:
    return s.NotificationSerializer(notification, context={"request": request}).data


def _flag(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    return value.lower() in ("1", "true", "yes")


class NotificationListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("unread", bool), OpenApiParameter("category", str)],
        responses=paginated(s.NotificationSerializer, style="cursor"),
    )
    def get(self, request: Request) -> Response:
        qs = selectors.feed(
            request.user,
            unread=_flag(request.query_params.get("unread")),
            category=request.query_params.get("category") or None,
        )
        paginator = FeedPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            s.NotificationSerializer(page, many=True, context={"request": request}).data
        )


class NotificationCountsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.NotificationCountsSerializer)
    def get(self, request: Request) -> Response:
        return Response(selectors.counts(request.user))


class NotificationDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.NotificationSerializer)
    def get(self, request: Request, notification_id: Any) -> Response:
        return Response(_item(request, services.get_notification(user=request.user, notification_id=notification_id)))

    @extend_schema(responses={204: None})
    def delete(self, request: Request, notification_id: Any) -> Response:
        services.delete_notification(user=request.user, notification_id=notification_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MarkReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    read = True

    @extend_schema(request=None, responses=s.NotificationSerializer)
    def post(self, request: Request, notification_id: Any) -> Response:
        action = services.mark_read if self.read else services.mark_unread
        return Response(_item(request, action(user=request.user, notification_id=notification_id)))


class MarkUnreadView(MarkReadView):
    read = False


class ReadAllView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.NotificationReadAllSerializer, responses=s.NotificationUpdatedSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.NotificationReadAllSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = services.mark_all_read(
            user=request.user,
            category=serializer.validated_data.get("category"),
            before=serializer.validated_data.get("before"),
        )
        return Response({"updated": updated})


class SeenView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses=s.NotificationUpdatedSerializer)
    def post(self, request: Request) -> Response:
        return Response({"updated": services.mark_all_seen(user=request.user)})


class CategoryListView(APIView):
    """Categories with their defaults and the caller's effective setting per channel.

    Change preferences through Core's ``me/notifications/`` endpoint.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.NotificationCategorySerializer(many=True))
    def get(self, request: Request) -> Response:
        from university.users.services.preferences import get_notification_settings

        prefs = get_notification_settings(request.user)
        channels = [Channel.IN_APP.value, *enabled_channels()]
        data = [
            {
                "key": c.key,
                "label": c.label,
                "mandatory": c.mandatory,
                "bypass_quiet_hours": c.bypass_quiet_hours,
                "channels": {
                    ch: {"default": c.defaults.get(ch, False), "effective": channel_mode(prefs, c, ch)}
                    for ch in channels
                },
            }
            for c in categories()
        ]
        return Response(data)


class DeviceListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.PushDeviceSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.PushDeviceSerializer(selectors.devices(request.user), many=True).data)

    @extend_schema(request=s.PushDeviceRegisterSerializer, responses={201: s.PushDeviceSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.PushDeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = services.register_device(user=request.user, **serializer.validated_data)
        return Response(s.PushDeviceSerializer(device).data, status=status.HTTP_201_CREATED)


class DeviceDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, device_id: Any) -> Response:
        services.unregister_device(user=request.user, device_id=device_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeviceUnregisterView(APIView):
    """Unregister by token — for sign-out flows where the app knows only its token."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.PushDeviceUnregisterSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        serializer = s.PushDeviceUnregisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.unregister_device(user=request.user, token=serializer.validated_data["token"])
        return Response(status=status.HTTP_204_NO_CONTENT)
