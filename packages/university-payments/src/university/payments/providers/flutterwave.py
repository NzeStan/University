"""Flutterwave v3 (https://developer.flutterwave.com/). Amounts are in major units."""

from __future__ import annotations

import urllib.parse
from typing import Any

from django.utils.dateparse import parse_datetime

from university.core.crypto import constant_time_equals
from university.core.exceptions import ProviderError
from university.core.providers.http import request
from university.core.webhooks import WebhookVerificationError
from university.payments.money import to_major, to_minor
from university.payments.providers import (
    Checkout,
    ProviderRefund,
    ProviderTransaction,
    WebhookNotice,
    json_payload,
)

STATUS = {"successful": "succeeded", "failed": "failed", "cancelled": "abandoned"}


class FlutterwaveProvider:
    label = "Flutterwave"
    API = "https://api.flutterwave.com/v3"

    def __init__(self, *, key: str = "flutterwave", secret_key: str, webhook_hash: str, timeout: int = 20) -> None:
        if not (secret_key and webhook_hash):
            raise ValueError("FlutterwaveProvider needs secret_key and webhook_hash.")
        self.key = key
        self.secret_key = secret_key
        self.webhook_hash = webhook_hash
        self.timeout = timeout

    def _call(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        data = request(
            method,
            f"{self.API}{path}",
            json_body=body,
            headers={"Authorization": f"Bearer {self.secret_key}"},
            timeout=self.timeout,
        )
        if not isinstance(data, dict) or data.get("status") != "success":
            raise ProviderError(code="flutterwave_error")
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
            "/payments",
            {
                "tx_ref": reference,
                "amount": str(to_major(amount_minor, currency)),
                "currency": currency,
                "redirect_url": callback_url,
                "customer": {"email": email},
                "customizations": {"title": description[:100]},
                "meta": metadata,
            },
        )
        return Checkout(checkout_url=data.get("link", ""))

    def verify(self, reference: str, provider_reference: str = "") -> ProviderTransaction:
        data = self._call("GET", f"/transactions/verify_by_reference?tx_ref={urllib.parse.quote(reference, safe='')}")
        currency = str(data.get("currency") or "").upper()
        return ProviderTransaction(
            status=STATUS.get(str(data.get("status")), "pending"),
            amount_minor=to_minor(data.get("amount") or 0, currency or "NGN"),
            currency=currency,
            provider_transaction_id=str(data.get("id") or ""),
            paid_at=parse_datetime(data["created_at"]) if data.get("created_at") else None,
            channel=str(data.get("payment_type") or "")[:32],
        )

    def refund(
        self, *, provider_transaction_id: str, reference: str, amount_minor: int, currency: str
    ) -> ProviderRefund:
        data = self._call(
            "POST",
            f"/transactions/{urllib.parse.quote(provider_transaction_id, safe='')}/refund",
            {"amount": str(to_major(amount_minor, currency))},
        )
        status = str(data.get("status") or "pending").lower()
        return ProviderRefund(
            status="succeeded"
            if status in ("completed", "successful")
            else "failed"
            if status == "failed"
            else "pending",
            provider_refund_id=str(data.get("id") or ""),
        )

    def parse_webhook(self, req: Any) -> WebhookNotice:
        # Flutterwave sends the configured secret hash in ``verif-hash``.
        if not constant_time_equals(req.headers.get("verif-hash", ""), self.webhook_hash):
            raise WebhookVerificationError()
        payload = json_payload(req.body)
        event = str(payload.get("event", ""))
        data = payload.get("data") or {}
        return WebhookNotice(
            event_id=f"{event}:{data.get('id')}",
            event_type=event,
            reference=data.get("tx_ref") if event.startswith("charge.") else None,
        )
