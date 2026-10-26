"""University Payments — provider-agnostic payments, refunds, escrow and payouts.

An optional *level two* module that depends only on University Core::

    pip install university-payments

    INSTALLED_APPS = [..., *CORE_APPS, "university.payments"]

Modules sell things through Core's payable adapters
(:mod:`university.core.payables`); this module takes the money through a
configured :class:`~university.payments.providers.PaymentProvider` (Paystack,
Flutterwave, Stripe), verifies every payment with the provider, and keeps a
double-entry ledger of escrow, balances and payouts. Core never depends on a
payment provider.
"""

__version__ = "0.1.1"
