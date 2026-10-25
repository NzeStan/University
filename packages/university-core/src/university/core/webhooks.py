"""Secure inbound webhook handling.

Every webhook integration (payments, SMS delivery reports, social providers)
must:

1. verify the signature over the *raw* body with a constant-time comparison,
2. reject stale timestamps (replay window),
3. de-duplicate deliveries by provider event id (replay protection and
   idempotency),
4. log the delivery and its outcome.

:class:`WebhookView` implements that pipeline; providers subclass it::

    class PaystackWebhookView(WebhookView):
        provider = "paystack"

        def verify(self, request):
            verify_hmac_signature(request.body, request.headers["X-Paystack-Signature"],
                                  secret=..., algorithm="sha512")

        def get_event_id(self, payload):
            return str(payload["data"]["id"])

        def handle(self, event, payload): ...
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.conf import university_settings
from university.core.crypto import sha256_hex
from university.core.exceptions import UniversityError
from university.core.models import WebhookEvent


class WebhookVerificationError(UniversityError):
    status_code = 400
    default_code = "invalid_webhook"
    default_message = "Webhook verification failed."


def verify_hmac_signature(
    payload: bytes,
    signature: str,
    *,
    secret: str | bytes,
    algorithm: str = "sha256",
    timestamp: str | int | None = None,
    tolerance_seconds: int | None = None,
    signed_payload_format: str = "{timestamp}.{payload}",
    prefix: str = "",
) -> None:
    """Verify an HMAC signature over ``payload``; raise on failure.

    When ``timestamp`` is given it is included in the signed content using
    ``signed_payload_format`` and must be within ``tolerance_seconds`` of now.
    """
    if not signature:
        raise WebhookVerificationError()
    if timestamp is not None:
        try:
            ts = int(timestamp)
        except (TypeError, ValueError) as exc:
            raise WebhookVerificationError() from exc
        tolerance = tolerance_seconds
        if tolerance is None:
            tolerance = int(university_settings.get("WEBHOOKS.TIMESTAMP_TOLERANCE_SECONDS", 300))
        if abs(time.time() - ts) > tolerance:
            raise WebhookVerificationError("Webhook timestamp outside the allowed window.", code="stale_webhook")
        signed = signed_payload_format.format(timestamp=ts, payload=payload.decode("utf-8", "replace")).encode()
    else:
        signed = payload
    key = secret if isinstance(secret, bytes) else secret.encode()
    expected = prefix + hmac.new(key, signed, getattr(hashlib, algorithm)).hexdigest()
    if not hmac.compare_digest(expected.encode(), signature.strip().encode()):
        raise WebhookVerificationError()


def record_webhook_event(
    provider: str, external_id: str, payload: Any, *, event_type: str = "", raw: bytes = b""
) -> tuple[WebhookEvent, bool]:
    """Persist a delivery; returns ``(event, created)``. Duplicates are counted."""
    digest = sha256_hex(raw or json.dumps(payload, sort_keys=True, default=str))
    try:
        with transaction.atomic():
            event = WebhookEvent.objects.create(
                provider=provider,
                external_id=external_id[:255],
                event_type=event_type[:128],
                payload_sha256=digest,
                payload=payload,
            )
        return event, True
    except IntegrityError:
        WebhookEvent.objects.filter(provider=provider, external_id=external_id[:255]).update(attempts=F("attempts") + 1)
        return WebhookEvent.objects.get(provider=provider, external_id=external_id[:255]), False


class WebhookView(APIView):
    """Base view for signed, de-duplicated inbound webhooks."""

    provider: str = ""
    authentication_classes: list[Any] = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = "webhook"
    #: Store the payload on the WebhookEvent (disable for sensitive payloads).
    store_payload = True

    def verify(self, request: Request) -> None:
        raise NotImplementedError

    def get_event_id(self, payload: Any) -> str:
        raise NotImplementedError

    def get_event_type(self, payload: Any) -> str:
        return str(payload.get("type") or payload.get("event") or "") if isinstance(payload, dict) else ""

    def handle(self, event: WebhookEvent, payload: Any) -> None:
        raise NotImplementedError

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raw = request.body
        self.verify(request)
        try:
            payload = json.loads(raw or b"null")
        except ValueError as exc:
            raise WebhookVerificationError("Malformed webhook payload.") from exc
        event, created = record_webhook_event(
            self.provider,
            self.get_event_id(payload),
            payload if self.store_payload else None,
            event_type=self.get_event_type(payload),
            raw=raw,
        )
        if not created and event.status == WebhookEvent.Status.PROCESSED:
            return Response({"status": "duplicate"}, status=status.HTTP_200_OK)
        try:
            with transaction.atomic():
                self.handle(event, payload)
        except Exception as exc:
            WebhookEvent.objects.filter(pk=event.pk).update(status=WebhookEvent.Status.FAILED, error=type(exc).__name__)
            raise
        WebhookEvent.objects.filter(pk=event.pk).update(
            status=WebhookEvent.Status.PROCESSED, processed_at=timezone.now(), error=""
        )
        return Response({"status": "processed"}, status=status.HTTP_200_OK)
