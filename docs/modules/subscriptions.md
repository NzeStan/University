# university-subscriptions

Premium plans, paid a period at a time, granting **entitlements** that any module can check
through Core. It depends only on `university-core`; payments go through university-payments.

```bash
pip install university-subscriptions university-payments
```

```python
INSTALLED_APPS += ["university.payments", "university.subscriptions"]
```

Run the `university.subscriptions.sweep` task hourly.

## Flow (`/api/v1/subscriptions/`)

1. `GET plans/` lists plans, prices per interval and currency, and what each includes.
2. `POST me/` `{plan, interval, currency}` chooses a plan. The subscription's `payment_due`
   (`purpose`, `object_id`, amount) goes to `POST /api/v1/payments/checkout/`.
3. When payment succeeds the subscription is `active` for one interval.
4. Renewal is paid by the member from `RENEWAL_WINDOW_DAYS` before the end (no stored cards). A
   reminder goes out `REMINDER_DAYS` before. Unpaid, it becomes `past_due` and keeps its
   entitlements for `GRACE_DAYS`, then `expired`.
5. `POST me/cancel/` stops renewing (the plan lasts to the end of the paid period);
   `{"cancel": false}` undoes it. `DELETE me/` drops a plan that hasn't been paid for.

One live subscription per member. A double payment or a payment for the wrong amount is refused
and refunded by payments; a refunded period is taken back off the subscription.

## Entitlements

```python
from university.core.entitlements import has_entitlement, ensure_entitlement

if has_entitlement(request.user, "creator.analytics_pro"):
    ...
ensure_entitlement(request.user, "premium.inbox_filters")  # 403 premium_required
```

Providers implement `Hook.USER_ENTITLEMENTS`. Built in: `premium.ad_free` hides adverts in
promotions, and `premium.badge` adds `extras.premium` to public profiles.

## Configuration

`UNIVERSITY["SUBSCRIPTIONS"]`: `PLANS` (name, description, `prices[interval][currency]`,
`entitlements`), `ENTITLEMENT_LABELS`, `INTERVAL_DAYS`, `RENEWAL_WINDOW_DAYS`, `REMINDER_DAYS`,
`GRACE_DAYS`.

## Events

`subscriptions.subscription.activated`, `.renewed`, `.renewal_due` and `.expired` (ids only).
Members are notified in the `commerce` category.
