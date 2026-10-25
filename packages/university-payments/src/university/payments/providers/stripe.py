"""Stripe Checkout Sessions (https://docs.stripe.com/api). Amounts in minor units."""

from __future__ import annotations

import datetime as dt
import urllib.parse
from typing import Any

from university.core.exceptions import ProviderError
from university.core.providers.http import request
from university.core.webhooks import WebhookVerificationError, verify_hmac_signature
from university.payments.providers import (
    Checkout,
    ProviderRefund,
    ProviderTransaction,
    WebhookNotice,
    json_payload,
)


class StripeProvider:
    label = "Stripe"
    API = "https://api.stripe.com/v1"

    def __init__(self, *, key: str = "stripe", secret_key: str, webhook_secret: str, timeout: int = 20) -> None:
        if not (secret_key and webhook_secret):
            raise ValueError("StripeProvider needs secret_key and webhook_secret.")
        self.key = key
        self.secret_key = secret_key
        self.webhook_secret = webhook_secret
        self.timeout = timeout

    def _call(self, method: str, path: str, form: dict[str, str] | None = None) -> dict[str, Any]:
        data = request(
            method,
            f"{self.API}{path}",
            form=form,
            headers={"Authorization": f"Bearer {self.secret_key}"},
            timeout=self.timeout,
        )
        if not isinstance(data, dict) or "error" in data:
            raise ProviderError(code="stripe_error")
        return data

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
        form = {
            "mode": "payment",
            "success_url": callback_url,
            "cancel_url": callback_url,
            "client_reference_id": reference,
            "customer_email": email,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][unit_amount]": str(amount_minor),
            "line_items[0][price_data][product_data][name]": description[:200],
            "metadata[reference]": reference,
            "payment_intent_data[metadata][reference]": reference,
        }
        for k, v in metadata.items():
            form[f"metadata[{k}]"] = str(v)[:500]
        data = self._call("POST", "/checkout/sessions", form)
        return Checkout(checkout_url=data.get("url", ""), provider_reference=str(data.get("id", "")))

    def verify(self, reference: str, provider_reference: str = "") -> ProviderTransaction:
        if not provider_reference:
            raise ProviderError(code="stripe_session_unknown")
        session = self._call(
            "GET", f"/checkout/sessions/{urllib.parse.quote(provider_reference, safe='')}?expand[]=payment_intent"
        )
        if session.get("client_reference_id") != reference:
            raise ProviderError(code="stripe_reference_mismatch")
        intent = session.get("payment_intent") or {}
        paid = session.get("payment_status") == "paid"
        expired = session.get("status") == "expired"
        created = intent.get("created") if isinstance(intent, dict) else None
        return ProviderTransaction(
            status="succeeded" if paid else "abandoned" if expired else "pending",
            amount_minor=int(session.get("amount_total") or 0),
            currency=str(session.get("currency") or "").upper(),
            provider_transaction_id=str(intent.get("id") if isinstance(intent, dict) else intent or ""),
            paid_at=dt.datetime.fromtimestamp(created, tz=dt.UTC) if created else None,
            channel="card",
        )

    def refund(
        self, *, provider_transaction_id: str, reference: str, amount_minor: int, currency: str
    ) -> ProviderRefund:
        data = self._call("POST", "/refunds", {"payment_intent": provider_transaction_id, "amount": str(amount_minor)})
        status = str(data.get("status") or "pending")
        return ProviderRefund(
            status="succeeded"
            if status == "succeeded"
            else "failed"
            if status in ("failed", "canceled")
            else "pending",
            provider_refund_id=str(data.get("id") or ""),
        )

    def parse_webhook(self, req: Any) -> WebhookNotice:
        header = req.headers.get("Stripe-Signature", "")
        parts: dict[str, list[str]] = {}
        for item in header.split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                parts.setdefault(k.strip(), []).append(v.strip())
        timestamp = (parts.get("t") or [None])[0]
        signatures = parts.get("v1") or []
        if not timestamp or not signatures:
            raise WebhookVerificationError()
        for i, signature in enumerate(signatures):
            try:
                verify_hmac_signature(req.body, signature, secret=self.webhook_secret, timestamp=timestamp)
                break
            except WebhookVerificationError:
                if i == len(signatures) - 1:
                    raise
        payload = json_payload(req.body)
        event_type = str(payload.get("type", ""))
        obj = (payload.get("data") or {}).get("object") or {}
        reference = None
        if event_type.startswith("checkout.session."):
            reference = obj.get("client_reference_id")
        elif event_type.startswith("charge.refund") or event_type.startswith("refund."):
            return WebhookNotice(
                event_id=str(payload.get("id", "")),
                event_type=event_type,
                provider_refund_id=str(obj.get("id") or ""),
                refund_status={"succeeded": "succeeded", "failed": "failed"}.get(str(obj.get("status")), "pending"),
            )
        return WebhookNotice(event_id=str(payload.get("id", "")), event_type=event_type, reference=reference)
