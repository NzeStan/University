# university-promotions

Adverts and boosted posts, reviewed before they run and paid for through university-payments. It
depends only on `university-core`.

```bash
pip install university-promotions university-payments
```

```python
INSTALLED_APPS += ["university.payments", "university.promotions"]
```

Run the `university.promotions.complete_finished` task every few minutes.

## Campaigns

- **Boost:** promote something you posted (`BOOSTABLE` content types: posts, events, listings,
  opportunities, podcasts). It must be yours and publicly visible.
- **Ad:** a headline, body, image, call to action and an `https` destination.

A campaign is a draft until submitted. With `REQUIRE_PAYMENT` it waits for payment (purpose
`promotions.campaign`, the platform is the payee), then goes to review. A reviewer
(`promotions.review`, role `ads_reviewer`) approves or rejects it, and can't review their own
campaigns. Rejecting a paid campaign refunds it in full through `payments.refund.requested`.

The budget buys impressions at `CPM_MINOR` per thousand. A campaign completes when its budget is
spent or its schedule ends; advertisers can pause and resume it.

## Delivery (`/api/v1/promotions/`)

- `GET serve/?placement=feed` returns up to `MAX_ITEMS_PER_REQUEST` items, each labelled
  **"Sponsored"** by the API. Targeting is by placement and, optionally, institution.
- Each item carries a **signed token**. `POST impressions/` and `POST clicks/` count only valid
  tokens, once each, so counts and spend can't be forged.
- A frequency cap (`DAILY_FREQUENCY_CAP`) uses short-lived keyed hashes in the cache. No viewer is
  stored: stats are daily aggregates per campaign (`GET campaigns/{id}/stats/`).
- Viewers holding `AD_FREE_ENTITLEMENT` (`premium.ad_free`, e.g. from a subscription) see boosts
  but no adverts.

Other endpoints: `GET options/`, `GET/POST campaigns/`, `GET/PATCH campaigns/{id}/`,
`POST .../image/`, `.../submit/`, `.../pause/`, `.../resume/`, `.../review/`, `GET review-queue/`.

## Reports

Running adverts are reportable. Platform moderators and ads reviewers investigate, never the
advertiser. They may hide the advert (it's rejected), restore it to review, or remove it. Boosts
are reported through the boosted content itself.

## Events

`promotions.campaign.submitted`, `.reviewed` (with `approved`) and `.completed` (ids only). The
advertiser is notified in the `promotions` category.
