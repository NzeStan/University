"""A deterministic provider for development and tests. Never enable it in production.

Payments succeed when :data:`OUTCOMES` says so (``mark_paid(reference)``);
webhooks are signed with HMAC-SHA256 of the raw body under ``webhook_secret``
in ``X-Test-Signature``.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from university.core.webhooks import verify_hmac_signature
from university.payments.providers import (
    Checkout,
    ProviderRefund,
    ProviderTransaction,
    WebhookNotice,
    json_payload,
)

#: reference -> ProviderTransaction
OUTCOMES: dict[str, ProviderTransaction] = {}
#: Refund behaviour: "succeeded", "pending", "failed" or "error" (raise).
REFUND_MODE: dict[str, str] = {"mode": "succeeded"}
INITIALIZED: list[dict[str, Any]] = []


def mark_paid(reference: str, amount_minor: int, currency: str, txn_id: str | None = None) -> None:
    OUTCOMES[reference] = ProviderTransaction(
        status="succeeded",
        amount_minor=amount_minor,
        currency=currency,
        provider_transaction_id=txn_id or f"txn_{reference}",
        paid_at=timezone.now(),
        channel="test",
    )


def reset() -> None:
    OUTCOMES.clear()
    INITIALIZED.clear()
    REFUND_MODE["mode"] = "succeeded"


class TestPaymentProvider:
    label = "Test payments"

    def __init__(self, *, key: str = "test", webhook_secret: str = "test-webhook-secret") -> None:  # noqa: S107
        self.key = key
        self.webhook_secret = webhook_secret

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
        INITIALIZED.append(
            {
                "reference": reference,
                "amount_minor": amount_minor,
                "currency": currency,
                "email": email,
                "metadata": metadata,
                "callback_url": callback_url,
            }
        )
        return Checkout(checkout_url=f"https://pay.test.invalid/{reference}", provider_reference=f"sess_{reference}")

    def verify(self, reference: str, provider_reference: str = "") -> ProviderTransaction:
        return OUTCOMES.get(reference) or ProviderTransaction(status="pending", amount_minor=0, currency="")

    def refund(
        self, *, provider_transaction_id: str, reference: str, amount_minor: int, currency: str
    ) -> ProviderRefund:
        mode = REFUND_MODE["mode"]
        if mode == "error":
            from university.core.exceptions import ProviderError

            raise ProviderError(code="test_refund_error")
        return ProviderRefund(status=mode, provider_refund_id=f"rf_{reference}")

    def parse_webhook(self, req: Any) -> WebhookNotice:
        verify_hmac_signature(req.body, req.headers.get("X-Test-Signature", ""), secret=self.webhook_secret)
        payload = json_payload(req.body)
        return WebhookNotice(
            event_id=str(payload.get("id", "")),
            event_type=str(payload.get("type", "")),
            reference=payload.get("reference"),
            provider_refund_id=str(payload.get("refund_id", "")),
            refund_status=str(payload.get("refund_status", "")),
        )
