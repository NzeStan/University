"""Paystack (https://paystack.com/docs/api/). Amounts are already in minor units."""

from __future__ import annotations

import urllib.parse
from typing import Any

from django.utils.dateparse import parse_datetime

from university.core.exceptions import ProviderError
from university.core.providers.http import request
from university.core.webhooks import verify_hmac_signature
from university.payments.providers import (
    Checkout,
    ProviderRefund,
    ProviderTransaction,
    WebhookNotice,
    json_payload,
)

STATUS = {"success": "succeeded", "failed": "failed", "abandoned": "abandoned", "reversed": "failed"}


class PaystackProvider:
    label = "Paystack"
    API = "https://api.paystack.co"

    def __init__(self, *, key: str = "paystack", secret_key: str, timeout: int = 20) -> None:
        if not secret_key:
            raise ValueError("PaystackProvider needs secret_key.")
        self.key = key
        self.secret_key = secret_key
        self.timeout = timeout

    def _call(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        data = request(
            method,
            f"{self.API}{path}",
            json_body=body,
            headers={"Authorization": f"Bearer {self.secret_key}"},
            timeout=self.timeout,
        )
        if not isinstance(data, dict) or not data.get("status"):
            raise ProviderError(code="paystack_error")
        return data.get("data") or {}

    def initialize(
        self,
        *,
        reference: str,
        amount_minor: int,
        currency: str,
        email: str,
        description: str,
        callback_url: str,
        metadata: dict[str, Any],
    ) -> Checkout:
        data = self._call(
            "POST",
            "/transaction/initialize",
            {
                "email": email,
                "amount": amount_minor,
                "currency": currency,
                "reference": reference,
                "callback_url": callback_url,
                "metadata": {**metadata, "description": description},
            },
        )
        return Checkout(checkout_url=data.get("authorization_url", ""), provider_reference=data.get("access_code", ""))

    def verify(self, reference: str, provider_reference: str = "") -> ProviderTransaction:
        data = self._call("GET", f"/transaction/verify/{urllib.parse.quote(reference, safe='')}")
        paid_at = parse_datetime(data["paid_at"]) if data.get("paid_at") else None
        return ProviderTransaction(
            status=STATUS.get(str(data.get("status")), "pending"),
            amount_minor=int(data.get("amount") or 0),
            currency=str(data.get("currency") or "").upper(),
            provider_transaction_id=str(data.get("id") or ""),
            paid_at=paid_at,
            channel=str(data.get("channel") or "")[:32],
        )

    def refund(
        self, *, provider_transaction_id: str, reference: str, amount_minor: int, currency: str
    ) -> ProviderRefund:
        data = self._call("POST", "/refund", {"transaction": provider_transaction_id, "amount": amount_minor})
        status = str(data.get("status") or "pending")
        return ProviderRefund(
            status="succeeded" if status == "processed" else "failed" if status == "failed" else "pending",
            provider_refund_id=str(data.get("id") or ""),
        )

    def parse_webhook(self, req: Any) -> WebhookNotice:
        signature = req.headers.get("X-Paystack-Signature", "")
        verify_hmac_signature(req.body, signature, secret=self.secret_key, algorithm="sha512")
        payload = json_payload(req.body)
        event = str(payload.get("event", ""))
        data = payload.get("data") or {}
        if event.startswith("refund."):
            return WebhookNotice(
                event_id=f"{event}:{data.get('id')}",
                event_type=event,
                reference=data.get("transaction_reference"),
                provider_refund_id=str(data.get("id") or ""),
                refund_status={"refund.processed": "succeeded", "refund.failed": "failed"}.get(event, "pending"),
            )
        return WebhookNotice(
            event_id=f"{event}:{data.get('id')}",
            event_type=event,
            reference=data.get("reference") if event.startswith("charge.") else None,
        )
