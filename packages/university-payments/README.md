# university-payments

Provider-agnostic payments for the [University platform](https://github.com/NzeStan/University):
Paystack, Flutterwave and Stripe adapters, verified webhooks, refunds, an escrow ledger and payouts.
This is an optional *level two* module that depends only on `university-core`. Core never depends
on a payment provider.

- **Sells for any module.**
  - Events (tickets), marketplace (orders) and creator (sponsorship fees) describe what's owed
    through Core's payable adapters. No module imports another.
- **Built on mistrust.**
  - Amounts come from the selling module, never the client.
  - Success always comes from re-verifying with the provider, never from webhook bodies or
    redirects.
  - Amount and currency must match exactly.
  - Every state change is locked and idempotent.
  - Checkout requires an `Idempotency-Key`.
- **Verified webhooks** through Core's pipeline: provider signatures (HMAC-SHA512, Stripe's
  timestamped signatures, Flutterwave's hash), replay protection, de-duplication and logging.
- **Automatic refunds** when a seller can't fulfil (for example, a ticket hold expired before
  payment arrived), or when the wrong amount was paid.
- **Double-entry ledger.** Escrow is held until the selling module releases it, alongside
  available balances and platform fees. Payouts are requested by sellers and processed by
  finance with four-eyes checks and no stored account numbers.
- **Admin** is read-only; money moves only through audited services.

```bash
pip install university-payments
```

```python
INSTALLED_APPS += ["university.payments"]
UNIVERSITY = {
    "PAYMENTS": {
        "PROVIDERS": {
            "paystack": {
                "class": "university.payments.providers.paystack.PaystackProvider",
                "options": {"secret_key": os.environ["PAYSTACK_SECRET_KEY"]},
            }
        }
    }
}
```

See [the module documentation](../../docs/modules/payments.md).
