"""Payment providers behind one protocol.

Configure them in ``PAYMENTS.PROVIDERS``; Core and the selling modules never
see a provider. Adapters shipped here:

=================  =========================================================
``paystack``       :class:`~.paystack.PaystackProvider` (NGN, GHS, ZAR, KES, USD)
``flutterwave``    :class:`~.flutterwave.FlutterwaveProvider` (pan-African)
``stripe``         :class:`~.stripe.StripeProvider` (Checkout Sessions)
``test``           :class:`~.testing.TestPaymentProvider` (development and tests)
=================  =========================================================

Rules every adapter follows:

* Outbound calls use Core's HTTPS-only client with timeouts and no redirects.
* :meth:`PaymentProvider.parse_webhook` verifies the signature over the raw
  body before anything else; payload contents are then only used to find
  *which* payment to re-verify — amounts always come from :meth:`verify`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Protocol

from django.utils.module_loading import import_string

from university.core.exceptions import NotFound, ValidationError
from university.payments.conf import payments_settings


@dataclass(frozen=True)
class Checkout:
    checkout_url: str
    #: The provider's handle for the checkout (session id, access code …).
    provider_reference: str = ""


@dataclass(frozen=True)
class ProviderTransaction:
    #: ``succeeded``, ``failed``, ``pending`` or ``abandoned``.
    status: str
    amount_minor: int
    currency: str
    provider_transaction_id: str = ""
    paid_at: dt.datetime | None = None
    channel: str = ""


@dataclass(frozen=True)
class ProviderRefund:
    #: ``succeeded``, ``pending`` or ``failed``.
    status: str
    provider_refund_id: str = ""


@dataclass(frozen=True)
class WebhookNotice:
    """What a verified webhook tells us — never trusted for amounts."""

    event_id: str
    event_type: str = ""
    #: Our payment reference, when the event concerns a payment.
    reference: str | None = None
    #: For refund events.
    provider_refund_id: str = ""
    refund_status: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class PaymentProvider(Protocol):
    key: str
    label: str

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
    ) -> Checkout: ...

    def verify(self, reference: str, provider_reference: str = "") -> ProviderTransaction: ...

    def refund(
        self, *, provider_transaction_id: str, reference: str, amount_minor: int, currency: str
    ) -> ProviderRefund: ...

    def parse_webhook(self, request: Any) -> WebhookNotice: ...


def json_payload(body: bytes) -> dict[str, Any]:
    """Parse a verified webhook body (always after signature verification)."""
    import json

    from university.core.webhooks import WebhookVerificationError

    try:
        payload = json.loads(body or b"{}")
    except ValueError as exc:
        raise WebhookVerificationError("Malformed webhook payload.") from exc
    return payload if isinstance(payload, dict) else {}


_cache: dict[str, tuple[Any, Any]] = {}


def providers() -> dict[str, PaymentProvider]:
    out: dict[str, PaymentProvider] = {}
    for key, conf in (payments_settings.get("PROVIDERS") or {}).items():
        if not conf:
            continue
        cached = _cache.get(key)
        if cached is None or cached[0] != conf:
            cls = import_string(conf["class"])
            cached = (conf, cls(key=key, **(conf.get("options") or {})))
            _cache[key] = cached
        out[key] = cached[1]
    return out


def get_provider(key: str | None) -> PaymentProvider:
    key = key or payments_settings.get("DEFAULT_PROVIDER")
    available = providers()
    if not key and len(available) == 1:
        key = next(iter(available))
    provider = available.get(key) if key else None
    if provider is None:
        raise ValidationError(details={"provider": ["Payment provider not available."]}, code="provider_unavailable")
    return provider


def get_provider_or_404(key: str) -> PaymentProvider:
    provider = providers().get(key)
    if provider is None:
        raise NotFound()
    return provider


def reset_providers() -> None:
    _cache.clear()
