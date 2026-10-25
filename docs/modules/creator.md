# university-creator

The creator economy: creator profiles, verification, linked social accounts, media kits,
sponsorship campaigns and analytics. It depends only on `university-core`, and every external
platform is reached through a provider adapter.

```bash
pip install university-creator
```

```python
INSTALLED_APPS += ["university.creator"]
```

## Profiles

Anyone can opt in (`POST me/creator/`) with a headline, bio, up to `MAX_CATEGORIES_PER_PROFILE`
categories, location, languages, a business email and whether they're open to sponsorships.

- **Privacy.** A creator page follows the account's own privacy settings and blocks (Core's
  `can_view_profile`, which social extends with blocks). Discovery lists only public, searchable
  accounts. Creators can pause their page (`status: "paused"`) or leave discovery
  (`is_discoverable: false`).
- **Badge.** Core's public profile gains `creator: {verified, headline, categories}` through
  `users.public_profile`.
- **Categories** are seeded from `CREATOR.CATEGORIES` on migrate; admins can rename, reorder or
  deactivate them.
- **Discovery** (`GET creators/?q=&category=&country=&verified=&open_to_sponsorships=&min_reach=`)
  is ordered by verified reach.

## Verification

A creator submits a statement and links (`POST me/creator/verification/`). Reviewers holding
`creator.verify` (the `creator_reviewer` role) approve or reject; nobody can review their own
request. Verification can be revoked with a reason. Every decision is audited and notified.

## Linked accounts and providers

Every platform is a `SocialProvider` adapter (spec §54):

```python
class SocialProvider(Protocol):
    key: str
    label: str
    supports_lookup: bool

    def profile_url(self, handle: str) -> str: ...
    def fetch_profile(self, handle: str) -> ExternalProfile | None: ...
```

| Provider | Ships as | Ownership | Follower counts |
| --- | --- | --- | --- |
| TikTok, Instagram, X, Facebook, Spotify, LinkedIn, Twitch, Audiomack, Boomplay | `ManualProvider` (profile URL template) | a reviewer confirms (`creator/linked-accounts/{id}/confirm/`) | self-reported, or set by the reviewer |
| YouTube | `ManualProvider`, or `YouTubeProvider` with an API key | **automatic**: the creator puts a challenge code (`UNIV-XXXXXXXX`) in their bio, then calls `verify/` | from the platform, refreshed by `sync_creator_accounts` |

Add, replace or remove platforms in `CREATOR.PROVIDERS` (set one to `None` to remove it).

Integrity rules:

- Only **verified** accounts with **provider- or reviewer-confirmed** counts add to
  `verified_reach`, which is what campaign requirements use. Self-reported numbers never do.
- A verified external account belongs to one creator only. A database constraint enforces this,
  so impersonators get `409 account_claimed`.
- Challenge codes are visible only to the owner. No platform passwords or OAuth tokens are
  stored.
- Daily follower snapshots feed growth charts.

## Media kits

`PATCH me/creator/media-kit/` sets:

- a summary;
- a self-reported audience breakdown (validated percentages, for example
  `{"age": {"18-24": 70}, "countries": {"NG": 85}}`);
- a rate card (`deliverable`, `price_minor`, `currency`);
- highlights (https links only);
- whether to show live platform stats (on-platform followers from social, if installed, plus
  verified reach).

| Visibility | Who can open `GET creators/{handle}/media-kit/` |
| --- | --- |
| `private` (default) | only the creator |
| `unlisted` | anyone with `?token=` (rotate with `POST me/creator/media-kit/rotate-link/` to revoke old links) |
| `public` | anyone who can see the creator |

## Campaigns and sponsorships

Brands run campaigns: a brief, categories, slots, a budget, dates and requirements (verified
only, minimum verified reach, disclosure required). Running one needs a verified email
(`CAMPAIGN_POLICY: "verified_users"`), or `creator.campaigns.manage` under `"permission"`. A
campaign for a sponsor scope (an institution or community) needs that permission at the scope:
the `campaign_manager` role.

```
creator applies ─► applied ─► shortlisted ─► accepted ─► completed (all deliverables approved)
brand invites  ─► invited ───────────────────┘   │
                     └► declined / withdrawn      └► cancelled (either side; the slot frees up)
```

- Accepting is limited by **slots** (row lock plus a database check), and requirements are
  checked for both applications and invitations.
- Invite-only campaigns are visible to their participants only. Blocks hide the campaign from the
  creator, and stop invitations in the other direction.
- **Deliverables:** the brand adds them; the creator submits a link and, when the campaign
  requires it, **confirms the content is labelled as sponsored (#ad)**. The brand approves or
  requests changes (with a note).
- **Paying fees:** the brand pays an accepted creator's agreed fee as the
  `creator.participation` payable (`POST payments/checkout/`). The money is held in escrow for the
  creator, released when the brand completes the collaboration, and refunded if it's cancelled.
  The platform commission is `PLATFORM_FEE_BPS`.

### Reporting policy

Campaigns are a known scam vector (fake brand deals), so they **opt in to moderation**:

- Reports go to the sponsor scope's moderators, otherwise platform moderators.
- Moderators can hide (managers only, and it can't be reopened), restore, or remove (cancels the
  campaign and every open or accepted participation, notifying creators).

Creator pages and media kits belong to the account and are reported through `users.user`.

## Analytics

`GET me/creator/analytics/?from=&to=&metrics=` returns daily series and totals:

| Metric | Source |
| --- | --- |
| `followers_gained` / `followers_lost`, `posts_published`, `reactions_received`, `comments_received`, `reposts_received`, `mentions` | ids-only social events (self-interactions excluded) |
| `profile_views`, `media_kit_views` | views of creator pages; the creator's own views and repeats within `VIEW_DEDUPE_HOURS` don't count |
| linked account follower series | daily snapshots |

Privacy by design (spec §55):

- Only per-day counters are stored, never who viewed or interacted.
- View de-duplication uses a short-lived keyed hash in the cache.
- Counters are kept for `ANALYTICS_RETENTION_DAYS`.
- Analytics are private to the creator and to support staff with `creator.analytics.view`.

## API (`/api/v1/…`)

| Method & path | Who |
| --- | --- |
| `GET creator-categories/` · `GET creator-providers/` | anyone |
| `GET creators/` · `GET creators/{handle-or-id}/` · `GET creators/{…}/media-kit/` | anyone (privacy applies) |
| `GET/POST/PATCH me/creator/` | users |
| `GET/POST me/creator/linked-accounts/` · `PATCH/DELETE …/{id}/` · `POST …/{id}/verify/` | creators |
| `GET/POST/DELETE me/creator/verification/` | creators |
| `GET/PATCH me/creator/media-kit/` · `POST me/creator/media-kit/rotate-link/` | creators |
| `GET me/creator/analytics/` · `GET me/creator/campaigns/` | creators |
| `GET creator/verification-requests/?status=` · `POST …/{id}/approve/` · `reject/` | `creator.verify` |
| `GET creator/linked-accounts/` · `POST …/{id}/confirm/` · `POST creators/{id}/revoke-verification/` | `creator.verify` |
| `GET creators/{id}/analytics/` | `creator.analytics.view` |
| `GET/POST campaigns/` · `GET/PATCH campaigns/{id}/` · `POST …/publish/` · `close/` · `complete/` · `cancel/` | anyone / brands |
| `GET campaigns/{id}/participations/` · `POST campaigns/{id}/invitations/` | brands |
| `POST campaigns/{id}/apply/` | creators |
| `POST participations/{id}/decision/` `{action, fee_minor?, note?}` | the creator or the brand (allowed actions depend on who calls) |
| `GET/POST participations/{id}/deliverables/` · `POST deliverables/{id}/submit/` · `review/` | the creator / the brand |
| `GET me/campaigns/` | brands |

Throttles: `creator_verification` (3/day), `creator_link_account` (30/day),
`creator_verify_account` (20/hour), `creator_campaign_create` (10/day), `creator_campaign_apply`
(30/day), `creator_campaign_invite` (100/day).

## Operations

- **Scheduled job:** `python manage.py sync_creator_accounts` (hourly) refreshes accounts not
  synced within `SYNC_INTERVAL_HOURS`. Provider failures are isolated per account.
- **Export:** profile, linked accounts (without challenge codes), verification requests, media
  kit, participations and owned campaigns.
- **Purge:** deletes the creator profile and everything under it (accepted deals free their
  slots), and cancels open campaigns the person owned.
- **Retention:** `creator.analytics` and `creator.follower_snapshots` (`ANALYTICS_RETENTION_DAYS`,
  730).
