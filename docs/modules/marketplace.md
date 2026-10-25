# university-marketplace

A campus marketplace: listings, sellers, categories, inventory, orders, disputes, reviews and
reports (spec §51). It depends only on `university-core`. Online orders are paid through any
payments module via Core's payable contract (normally `university-payments`), and cash on pickup
works without one.

```bash
pip install university-marketplace university-payments
```

```python
INSTALLED_APPS += ["university.marketplace", "university.payments"]
```

## Listings

- **Content:** title, description, category, condition, price (minor units), currency and
  **stock**.
- **Fulfilment:** pickup and/or delivery (with a delivery fee), and whether cash on pickup is
  accepted.
- **Images:** up to `MAX_IMAGES`, checked by content signature, size limited and stored under
  random names.
- **Categories** are a tree seeded from `MARKETPLACE.CATEGORIES`; browsing a parent includes its
  children.
- **Statuses:** draft → active ↔ paused; sold out when stock reaches zero (and back to active
  when restocked); removed.
- **Members-only listings:** `visibility: "audience"` with a scope (for example an institution)
  limits a listing to that audience. Sellers must belong to the scope.
- **Browsing** (`GET marketplace/listings/`): `q`, `category`, `condition`, `currency`, `city`,
  `scope_type`/`scope_id`, `seller`, `min_price`/`max_price`, `in_stock`, and `sort` (`price`,
  `-price`, newest by default). Blocks hide listings in both directions.

Selling needs a verified email (`REQUIRE_VERIFIED_EMAIL`), and each seller has at most
`MAX_ACTIVE_LISTINGS` listings. Spam screening and content-creation restrictions apply.

## Orders

`POST marketplace/orders/` `{listing, quantity, fulfilment, payment_method, delivery_details}`
requires an **`Idempotency-Key`**. Placing an order **reserves stock** under a row lock (a database
check stops stock going negative). The order keeps a snapshot of the title and price, and a
database check enforces `total = unit price × quantity + delivery fee`.

```
online:  pending_payment ─► paid ─► fulfilled ─► completed   (buyer confirms, or after AUTO_COMPLETE_DAYS)
              │               │          └──► disputed ─► completed (release / partial refund) or refunded
              └► cancelled    └► cancelled + full refund (seller)
         (unpaid after PAYMENT_WINDOW_MINUTES: cancelled, stock returned)
cash:    placed ─► completed (seller confirms the handover)   └► cancelled
free:    paid immediately
```

- **Paying:** `POST payments/checkout/` `{"purpose": "marketplace.order", "object_id": <order>}`.
  The seller's share, minus `PLATFORM_FEE_BPS`, is **held in escrow** and released when the order
  completes. A payment that arrives after the order expired is refunded automatically.
- **Buyer protection:** the buyer confirms delivery, or opens a **dispute** on a paid or fulfilled
  online order (which freezes auto-completion). Mediators (`marketplace.disputes.resolve`, the
  `marketplace_mediator` role) resolve it with a full refund, a partial refund (the rest goes to
  the seller), or a release. Nobody mediates their own order, and every decision is audited.
- **Cash on pickup** is available when the platform and the listing allow it, for pickup orders
  only. There's no escrow or disputes: the seller confirms the handover.
- **Cancellation:** buyers can cancel before paying; sellers can cancel up to fulfilment, and a
  paid order is then refunded in full. Stock is always returned exactly once.
- **Privacy:** `delivery_details` (address, phone) are visible only to the buyer and seller (not
  to mediators). They're excluded from the seller's data export and erased
  `DELIVERY_DETAILS_RETENTION_DAYS` after the order closes.

## Sellers and reviews

Seller profiles (store name, about, rating, sales count) are created on the first listing and
shown on public profiles as `seller: {...}`. Buyers review **completed** orders once (1–5 stars
and a comment), and sellers reply once. Ratings are recomputed when moderators hide a review.

## Trust and safety

| Content type | Who investigates | Actions |
| --- | --- | --- |
| `marketplace.listing` | the listing's scope moderators, otherwise platform moderators | hide (can't be republished), restore, remove: cancels open orders and refunds paid ones; sanctions apply to the seller |
| `marketplace.review` | platform moderators | hide, restore, remove (recomputes the rating); sanctions apply to the reviewer |

Disputes are decided by mediators, not moderation.

## API (`/api/v1/marketplace/…`)

| Method & path | Who |
| --- | --- |
| `GET categories/` | anyone |
| `GET/POST listings/` · `GET/PATCH listings/{id}/` · `POST listings/{id}/status/` `{publish\|pause\|remove}` | anyone / sellers |
| `POST listings/{id}/images/` · `DELETE listings/{id}/images/{image}/` | the seller |
| `GET sellers/{handle-or-id}/` · `GET sellers/{…}/reviews/` | anyone |
| `POST orders/` (Idempotency-Key) · `GET orders/{id}/` | buyers / the parties and mediators |
| `POST orders/{id}/cancel/` · `fulfil/` · `confirm/` · `complete/` · `dispute/` | the buyer or seller, as allowed |
| `POST orders/{id}/resolve/` `{outcome, refund_minor?, note}` · `GET disputes/` | mediators |
| `POST orders/{id}/review/` · `POST reviews/{id}/reply/` | the buyer / the seller |
| `GET/PATCH me/seller/` · `GET me/listings/` · `GET me/orders/?role=buyer\|seller` | users |

## Operations

- **Scheduled job:** `python manage.py marketplace_maintenance` (every few minutes) expires unpaid
  orders and auto-completes fulfilled ones.
- **Notifications** (with `university-notifications`): order placed, paid, fulfilled, completed,
  cancelled, disputed, dispute resolved, and review received.
- **Export:** listings, purchases (with your own delivery details), sales (without buyers'
  details) and reviews.
- **Purge:** listings are removed, unpaid orders cancelled, and delivery details erased. Order
  records are kept for the counterparty.
