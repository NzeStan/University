# university-payments

Provider-agnostic payments: checkout, verification, refunds, an escrow ledger and payouts. It
depends only on `university-core`, and Core never depends on a payment provider (spec §51).

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
            },
        },
        "DEFAULT_PROVIDER": "paystack",
        "CALLBACK_URL": "https://app.example.edu/payments/return?reference={reference}",
        "ALLOWED_CALLBACK_PREFIXES": ["https://app.example.edu/"],
    }
}
```

## How modules sell: payable adapters

Selling modules never import payments, and payments never imports them. They meet through Core's
**payable** contract (`university.core.payables`):

| Purpose | Contributed by | Payer | Payee and escrow |
| --- | --- | --- | --- |
| `marketplace.order` | marketplace | the buyer | the seller; escrow until the buyer confirms delivery |
| `events.registration` | events | the attendee | platform (no payee) |
| `creator.participation` | creator | the brand | the creator; escrow until the collaboration completes |

An adapter's `resolve(object_id, payer)` says what is owed now (and refuses the wrong payer or a
stale request). `on_paid(...)` fulfils the purchase; raising `Conflict` means "too late", and the
payment is refunded automatically. `on_refunded(...)` reacts to refunds. Selling modules ask for
money movements with events: `payments.release.requested` (release escrow) and
`payments.refund.requested` (refund, optionally partial).

## Checkout and verification

1. `POST /api/v1/payments/checkout/` `{purpose, object_id, provider?, callback_url?}` with an
   **`Idempotency-Key`** header (required). The amount comes from the adapter, never the client.
   Retrying reuses the open checkout instead of creating a second charge, and a client-supplied
   `callback_url` must match `ALLOWED_CALLBACK_PREFIXES` (open-redirect protection). The response
   includes `checkout_url`.
2. The payer pays on the provider's page and is sent back to `CALLBACK_URL`.
3. The app calls `POST payments/{reference}/verify/`, and/or the provider sends a webhook. Either
   way, **the result always comes from asking the provider** (`PaymentProvider.verify`). Webhook
   bodies and redirects are never trusted for amounts.
4. If the amount and currency match exactly, the intent succeeds, the ledger is posted and the
   adapter fulfils. A different amount is booked and refunded in full; a different currency is
   held for finance (`failure_reason: currency_mismatch`). A provider transaction can settle only
   one intent (database constraint).

Every step locks the intent and is idempotent: duplicate webhooks, repeated redirects and
concurrent workers can't fulfil twice. Unpaid checkouts expire (`INTENT_TTL_MINUTES`, or sooner if
the payable has a hold such as a ticket reservation).

## Webhooks

`POST /api/v1/payments/webhooks/<provider>/` runs on Core's secure webhook pipeline (spec §65):

| Provider | Signature check |
| --- | --- |
| Paystack | HMAC-SHA512 of the raw body (`X-Paystack-Signature`) |
| Flutterwave | the configured secret hash (`verif-hash`), compared in constant time |
| Stripe | `Stripe-Signature` (`t=…,v1=…`): HMAC-SHA256 of `t.payload`, with timestamp tolerance (replay window) |
| Test | HMAC-SHA256 (`X-Test-Signature`) — development only |

Deliveries are de-duplicated by event id (replay protection) and logged without storing payment
payloads. Notices for unknown references are acknowledged and ignored.

## Refunds

- **Automatic:** when fulfilment fails or the amount was wrong.
- **Requested by selling modules:** a seller cancels a paid order, a mediator resolves a dispute,
  an organizer declines a paid attendee or cancels the event, or a brand cancels a paid
  collaboration.
- **By finance:** `POST payments/{reference}/refunds/` `{amount_minor?, reason}` with
  `payments.refunds.manage`.

Refunds can't exceed what's refundable (pending refunds count). They're submitted as tasks, retried
up to `MAX_REFUND_ATTEMPTS`, and settled by the provider's response or webhook. Run
`python manage.py payments_maintenance` every few minutes to expire abandoned checkouts and retry
refunds.

## Ledger, balances and payouts

A **double-entry ledger** records every money movement as a balanced posting. Entries are never
edited or deleted.

| Account | Meaning |
| --- | --- |
| `provider:<key>` | money held at the provider |
| `payee:<user>:held` | a seller's or creator's escrowed share |
| `payee:<user>:available` | withdrawable balance |
| `payee:<user>:payout` | committed to requested payouts |
| `platform:revenue` | platform fees, and payee-less income such as tickets |
| `platform:payouts` | money paid out |

Platform fees (from the payable) are taken proportionally, including on partial refunds.

- `GET payments/me/balance/` → `[{currency, held, available, payout}]`.
- `POST payments/me/payouts/` `{amount_minor, currency, destination}` — up to the available
  balance and at least `MIN_PAYOUT_MINOR`. Destinations are **masked descriptions**
  ("GTBank ••••6789"); full account numbers are rejected and never stored.
- Finance officers (`payments.payouts.manage`) mark payouts **paid** (with the transfer
  reference) or **rejected**. Nobody processes their own payout. Payees can cancel requests that
  are still pending.

## API (`/api/v1/payments/…`)

| Method & path | Who |
| --- | --- |
| `GET providers/` | anyone |
| `POST checkout/` (Idempotency-Key required) | payers |
| `GET ./` · `GET {reference}/` · `POST {reference}/verify/` | the payer, or `payments.view` |
| `GET/POST {reference}/refunds/` | the payer (read) / `payments.refunds.manage` |
| `GET me/balance/` · `GET/POST me/payouts/` · `POST me/payouts/{id}/cancel/` | payees |
| `GET payouts/?status=` · `POST payouts/{id}/approve/` · `reject/` | `payments.payouts.manage` |
| `POST webhooks/{provider}/` | providers (signed) |

The admin is read-only: money moves only through audited services. The `finance_officer` role
holds `payments.*`.

## Operations

- **Health check:** `payments.refunds` (non-critical) turns unhealthy when refunds stay pending
  for more than six hours.
- **Export:** payments, payouts and balances.
- **Purge:** open checkouts are cancelled and the person is detached from payment records.
  Financial records themselves are kept for tax and anti-fraud obligations, and payout
  destinations are erased.
- **Adding a provider** (for example Opay, Monnify, MTN MoMo): implement `PaymentProvider`
  (`initialize`, `verify`, `refund`, `parse_webhook`) using Core's HTTPS client, then register it
  in `PAYMENTS.PROVIDERS`.
