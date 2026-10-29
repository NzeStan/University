# university-subscriptions

Premium plans, paid periods and entitlements other modules can check.

An optional **level-two** module of the University platform.

## Installation

```bash
pip install university-subscriptions university-payments
```

```python
INSTALLED_APPS = [
    # ...
    *CORE_APPS,
    "university.payments",
    "university.subscriptions",
]
```

Run `python manage.py migrate`. The API is mounted under `/api/v1/subscriptions/`.

## How it works

1. `GET plans/` lists the plans, prices and what each includes.
2. `POST me/` with `{plan, interval, currency}` chooses a plan. The response's `payment_due`
   is passed to `POST /api/v1/payments/checkout/` (purpose `subscriptions.period`).
3. When the payment succeeds the subscription becomes `active` for one interval.
4. Renewals are paid by the member (no stored cards) from `RENEWAL_WINDOW_DAYS` before the
   period ends. A reminder goes out `REMINDER_DAYS` before, and entitlements continue for
   `GRACE_DAYS` after an unpaid period ends, then the subscription expires.
5. `POST me/cancel/` stops renewing; the plan lasts until the paid period ends.

Run the `university.subscriptions.sweep` task (or call `services.sweep()`) every hour.

## Entitlements

Plans grant entitlement keys. Any module can check them through Core, without depending on
this package:

```python
from university.core.entitlements import has_entitlement

if has_entitlement(request.user, "creator.analytics_pro"):
    ...
```

`premium.ad_free` hides adverts in university-promotions; `premium.badge` adds `premium: true`
to public profiles.

## Configuration

```python
UNIVERSITY = {
    "SUBSCRIPTIONS": {
        "PLANS": {
            "plus": {
                "name": "Plus",
                "description": "No adverts and a profile badge.",
                "prices": {"month": {"NGN": 150000}, "year": {"NGN": 1500000}},
                "entitlements": ["premium.ad_free", "premium.badge"],
            },
        },
        "GRACE_DAYS": 3,
    },
}
```

A double payment, or a payment for the wrong amount, is refused and refunded by
university-payments. A refunded period is taken back off the subscription.
