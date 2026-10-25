"""Settings for the payments module (``UNIVERSITY["PAYMENTS"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    # Configured providers. Keys are used in webhook URLs (payments/webhooks/<key>/).
    # Keep secrets in the environment, never in source control, e.g.:
    #   "paystack": {"class": "university.payments.providers.paystack.PaystackProvider",
    #                "options": {"secret_key": os.environ["PAYSTACK_SECRET_KEY"]}},
    "PROVIDERS": {},
    # Used when a checkout doesn't name a provider.
    "DEFAULT_PROVIDER": None,
    # Where providers send the payer back. {reference} is substituted.
    "CALLBACK_URL": "http://localhost:3000/payments/return?reference={reference}",
    # Client-supplied callback URLs must start with one of these (open-redirect protection).
    "ALLOWED_CALLBACK_PREFIXES": ["http://localhost:3000/"],
    "CURRENCIES": ["NGN", "GHS", "KES", "ZAR", "XOF", "EGP", "USD"],
    # Unpaid checkouts expire after this long.
    "INTENT_TTL_MINUTES": 60,
    "MAX_REFUND_ATTEMPTS": 5,
    "MIN_PAYOUT_MINOR": {"NGN": 100000, "GHS": 1000, "KES": 10000, "ZAR": 1000, "XOF": 1000, "EGP": 1000, "USD": 500},
    "PAYMENT_RETENTION_DAYS": None,  # Financial records are usually kept for years; set per jurisdiction.
}

payments_settings = ModuleSettings("PAYMENTS", DEFAULTS)
