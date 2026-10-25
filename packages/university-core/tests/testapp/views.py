from __future__ import annotations

import itertools
from typing import Any

from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.exceptions import Conflict
from university.core.idempotency import idempotent
from university.core.webhooks import WebhookView, verify_hmac_signature
from university.permissions.drf import require_permission

COUNTER = itertools.count(1)
HANDLED: list[Any] = []
WEBHOOK_SECRET = "whsec_test"


class OrderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @idempotent("testapp.order.create")
    def post(self, request: Request) -> Response:
        if request.data.get("fail") == "conflict":
            raise Conflict()
        return Response({"order": next(COUNTER), "item": request.data.get("item")}, status=201)


class WidgetView(APIView):
    permission_classes = [permissions.IsAuthenticated, require_permission("testapp.widgets.view")]

    def get(self, request: Request) -> Response:
        return Response({"ok": True})


class PublicView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "testapp_public"

    def get(self, request: Request) -> Response:
        return Response({"ok": True})


class BoomView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request: Request) -> Response:
        raise RuntimeError("secret internal detail /etc/passwd")


class TestWebhookView(WebhookView):
    provider = "testpay"

    def verify(self, request: Request) -> None:
        verify_hmac_signature(
            request.body,
            request.headers.get("X-Signature", ""),
            secret=WEBHOOK_SECRET,
            timestamp=request.headers.get("X-Timestamp"),
        )

    def get_event_id(self, payload: Any) -> str:
        return str(payload["id"])

    def handle(self, event: Any, payload: Any) -> None:
        HANDLED.append(payload["id"])
