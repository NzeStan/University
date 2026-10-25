"""Inbound provider webhooks, on Core's secure pipeline.

``POST /api/v1/payments/webhooks/<provider>/``: the provider adapter verifies
the signature over the raw body, Core records and de-duplicates the delivery
(replay protection), and the payment is then re-verified with the provider
before anything changes.
"""

from __future__ import annotations

from typing import Any

from rest_framework.request import Request
from rest_framework.response import Response

from university.core.api.schema import extend_schema
from university.core.models import WebhookEvent
from university.core.webhooks import WebhookView
from university.payments.providers import WebhookNotice, get_provider_or_404


class PaymentWebhookView(WebhookView):
    store_payload = False  # Payment payloads can hold personal data; the event id suffices.

    @extend_schema(exclude=True)
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self.provider_obj = get_provider_or_404(kwargs["provider"])
        self.provider = self.provider_obj.key
        return super().post(request, *args, **kwargs)

    def verify(self, request: Request) -> None:
        self.notice: WebhookNotice = self.provider_obj.parse_webhook(request)

    def get_event_id(self, payload: Any) -> str:
        return self.notice.event_id or f"digest:{request_body_digest(payload)}"

    def get_event_type(self, payload: Any) -> str:
        return self.notice.event_type

    def handle(self, event: WebhookEvent, payload: Any) -> None:
        from university.payments.services import handle_notice

        handle_notice(self.provider, self.notice)


def request_body_digest(payload: Any) -> str:
    import json

    from university.core.crypto import sha256_hex

    return sha256_hex(json.dumps(payload, sort_keys=True, default=str))
