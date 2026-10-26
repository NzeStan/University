# Changelog

All notable changes to the University packages are documented here. Each package is versioned
independently following [Semantic Versioning](https://semver.org/). The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Sections per release: **Added**, **Changed**, **Deprecated** (with replacement and removal
version), **Removed**, **Fixed**, **Security**.

## [Unreleased]

### university-core

#### Added

- `university.core.content`: `ContentAdapter` / `ContentRef` / `get_adapter`, plus
  `UniversityAppConfig.get_content_adapters()`, so cross-cutting modules act on any module's
  content without imports.
- `Hook.USER_CAN_CREATE_CONTENT` and `ensure_can_create()`, so content-creation restrictions apply
  across every module.
- `permissions.services.scopes_with_permission()` for efficient scope-filtered queues.
- `ContentAdapter.moderatable` (default `False`), `get_moderatable_adapter()` and
  `content_types(moderatable=...)`. Registering a content adapter no longer implies it is
  reportable: moderation is an explicit opt-in. System check `university.E003` flags moderatable
  adapters that don't implement `hide`/`restore`/`remove`.
- `Hook.CONTENT_TRENDING_SCORES` (`content.trending_scores`): trending engines supply scores that feeds can rank by.
- `ContentAdapter.iter_ids()` (optional): live item ids for search backfills.
- `university.core.media`: the `MediaLibrary` contract (`MediaRef`, `get_media_library()`,
  `require_media_library()`) and `UniversityAppConfig.get_media_library()` (one provider per deployment).
- Upload signatures for MPEG-2/2.5 MP3 frames and AAC (ADTS) streams.
- `AuditOutcomeChoices`, an importable alias of the audit outcome choices (used for OpenAPI enum naming).
- `university.core.payables`: `PayableAdapter` / `Payable` / `get_payable_adapter()`, plus
  `UniversityAppConfig.get_payable_adapters()`. Modules sell things without depending on payments;
  `payments.release.requested` and `payments.refund.requested` are the event contract back.
- `AuditOutcomeEnum` in the default OpenAPI enum overrides.
- `OpenApiTypes.STR` in the no-drf-spectacular fallback.
- `extend_schema_field` exported from `university.core.api.schema` (no-op without drf-spectacular).
- `Hook.AUDIENCE_CAN_POST` with `audiences.can_post_to()` / `ensure_can_post_to()`: audiences can
  restrict who posts into them; social and anonymous enforce it for posts and comments.
- `Hook.PERMISSIONS_IMPLICIT_SCOPES`: implicitly granted permissions also count in scope-filtered queues.
- `Hook.SCOPE_MEMBERSHIPS` and `university.core.audiences` (`member_scopes`, `is_member`): modules
  can declare and consume audience membership (institution, campus, community) without coupling.

### university-institution

#### Added

- Implements `scopes.memberships`: verified members belong to their institution's audience, and to
  their campus's when one is set.
- A display-only `institution.institution` content adapter, so notifications show institution
  names. Institutions are not moderatable (not reportable or sanctionable).

### university-social

#### Added

- The `trending` feed (`RankedFeed`) ranks by `content.trending_scores` when a trending engine is
  installed; content adapters implement `iter_ids()`.
- Content adapters for `social.post` and `social.comment`; posting and commenting respect
  `content.can_create` restrictions.

### university-moderation

#### Changed

- Reports, moderator-opened cases and new actions accept only content types that opted in with
  `moderatable = True` (all existing moderation-facing adapters do). Display-only types return the
  same `404 Unknown content type.` as unknown ones.
- `moderation.appeal.decided` events include `appellant_id` for non-anonymous content, so the
  appellant can be notified. Anonymous authors are still never linked in payloads.

### university-notifications

#### Added

- `podcasts` (new episodes, grouped per show; guest invitations) and `media` (failed uploads) categories.
- A `commerce` category: marketplace order updates, disputes, reviews, refunds, unfulfilled
  payments and payouts.
- A `creator` category: verification decisions, campaign invitations, applications, acceptances,
  withdrawals, cancellations and deliverable reviews (sent to whichever side didn't act).
- An `events` category with notifications for registrations, waitlists, promotions (deduplicated
  against the following confirmation), declines, expired holds, cancellations, reschedules and
  reminders.

### university-events

#### Added

- Paid tickets sold as the `events.registration` payable; refunds for declined attendees, cancelled
  events and attendee cancellations before `REFUND_CUTOFF_HOURS`; full refunds cancel the ticket.

### university-creator

#### Added

- Sponsorship fees sold as the `creator.participation` payable with escrow: released on completion,
  refunded on cancellation; `PLATFORM_FEE_BPS`; `fee_paid_at` on participations.

### university-community

#### Changed

- Owners and admins hold `events.manage` and `podcast.manage` at their community's scope (unused unless
  `university-events` is installed), so they can host community events.

## university-events 0.1.1 — 2026-10-26

### Fixed

- Row locks combined with `select_related()` now lock only the target row (`select_for_update(of=("self",))`). PostgreSQL rejected the previous queries ("FOR UPDATE cannot be applied to the nullable side of an outer join"), and joined rows were being locked needlessly. This broke publishing events, organizer changes and cover uploads on PostgreSQL.

## university-search 0.1.1 — 2026-10-26

### Fixed

- PostgreSQL full-text search now filters on the match itself (`@@`). `ts_rank` gives non-matching documents a tiny non-zero rank, so every visible document was returned.

## university-creator 0.1.1 — 2026-10-26

### Fixed

- Row locks combined with `select_related()` now lock only the target row (`select_for_update(of=("self",))`). PostgreSQL rejected the previous queries ("FOR UPDATE cannot be applied to the nullable side of an outer join"), and joined rows were being locked needlessly.
- Public profiles list linked accounts in a stable order: verified first, then by follower count, then by provider and handle.

## university-community 0.1.1 — 2026-10-26

### Fixed

- Row locks combined with `select_related()` now lock only the target row (`select_for_update(of=("self",))`). PostgreSQL rejected the previous queries ("FOR UPDATE cannot be applied to the nullable side of an outer join"), and joined rows were being locked needlessly.

## university-institution 0.1.1 — 2026-10-26

### Fixed

- Row locks combined with `select_related()` now lock only the target row (`select_for_update(of=("self",))`). PostgreSQL rejected the previous queries ("FOR UPDATE cannot be applied to the nullable side of an outer join"), and joined rows were being locked needlessly.

## university-moderation 0.1.1 — 2026-10-26

### Fixed

- Row locks combined with `select_related()` now lock only the target row (`select_for_update(of=("self",))`). PostgreSQL rejected the previous queries ("FOR UPDATE cannot be applied to the nullable side of an outer join"), and joined rows were being locked needlessly.

## university-payments 0.1.1 — 2026-10-26

### Fixed

- Row locks combined with `select_related()` now lock only the target row (`select_for_update(of=("self",))`). PostgreSQL rejected the previous queries ("FOR UPDATE cannot be applied to the nullable side of an outer join"), and joined rows were being locked needlessly.

## university-podcast 0.1.1 — 2026-10-26

### Fixed

- Row locks combined with `select_related()` now lock only the target row (`select_for_update(of=("self",))`). PostgreSQL rejected the previous queries ("FOR UPDATE cannot be applied to the nullable side of an outer join"), and joined rows were being locked needlessly.

## university-analytics 0.1.0 — initial release

### Added

- Daily aggregate counters from ids-only events (platform-wide and per scope), with no raw events
  and no user ids; `TRACK`/`EXCLUDE` patterns and configurable dimensions.
- Daily/weekly/monthly active users counted with expiring keyed hashes; view recording for any
  visible content (deduplicated, no viewer stored) publishing `content.viewed`.
- Platform and scope (institution) dashboards with small-group suppression; minimised,
  monthly-pseudonymised warehouse sinks; retention.

## university-trending 0.1.0 — initial release

### Added

- Hourly signal buckets (views, reactions, comments, shares, registrations, joins, orders) with
  per-person deduplication and unique-actor counting; no user ids stored.
- A configurable gravity-plus-velocity algorithm (pluggable), a minimum of unique actors, author
  diversity, scoped lists, a per-viewer visibility check, and the `content.trending_scores` hook
  for feeds.

## university-search 0.1.0 — initial release

### Added

- Database (PostgreSQL full-text) and OpenSearch/Elasticsearch backends behind Core's search
  abstraction.
- Event-driven indexing through content adapters, visibility tags, a definitive per-viewer
  `can_view` check on every hit, and `search_reindex` backfills.
- Enumeration-resistant people search (never by email or phone; respects searchable, privacy and
  blocks); rate limits; purge by author.

## university-media 0.1.0 — initial release

### Added

- Uploads validated by content signature against per-kind allow-lists (audio, video, image, document),
  with size limits, quotas, a pending-upload cap, SHA-256 and random private storage names.
- Asynchronous processing (`BasicProcessor`, sandboxed `FFmpegProcessor`: MP3, 720p MP4, poster, clips)
  with duration and dimension limits.
- Presigned direct-to-storage uploads (S3) verified by size and signature on completion.
- Signed, expiring streaming links with HTTP Range support, or storage-native URLs; Core's media library
  with owner-only attachment and in-use protection.
- Orphan and failed-upload retention, a processing health check, export and purge (files included).

## university-podcast 0.1.0 — initial release

### Added

- Shows hosted by people or scopes with public, unlisted and members-only visibility; owner, host and
  producer teams granted through `permissions.implicit_grants`; seasons.
- Episodes with audio and video from the media library (owner-checked, published only when ready),
  scheduling, subscriber notifications and stable stream links.
- Guests with consent-based account links; transcripts (sanitised VTT, SRT or text; VTT export; automatic
  transcription behind `TranscriptionProvider`); asynchronous clips.
- RSS with iTunes and Podcasting 2.0 tags; de-duplicated, aggregate-only listening analytics.
- Moderatable shows and episodes routed to the host scope; export, purge with ownership succession, and
  retention.

## university-payments 0.1.0 — initial release

### Added

- Provider-agnostic checkout (Paystack, Flutterwave, Stripe and test adapters behind `PaymentProvider`)
  with a required Idempotency-Key, open-redirect-safe callbacks and reuse of open checkouts.
- Server-side verification of every payment, exact amount and currency matching, one intent per
  provider transaction, locked and idempotent state changes, and automatic refunds when fulfilment
  fails or the amount is wrong.
- Signed, de-duplicated webhooks on Core's pipeline (HMAC-SHA512, Stripe timestamped signatures,
  Flutterwave hash).
- Refunds (partial, automatic, requested, finance) with retries; a double-entry ledger with escrow,
  available balances and platform fees; payouts with masked destinations and four-eyes processing;
  a read-only admin, export, purge and a refunds health check.

## university-marketplace 0.1.0 — initial release

### Added

- Listings with a category tree, conditions, stock, images, pickup or delivery, and members-only
  scopes; browsing with filters and blocks.
- Orders that reserve stock (database-checked), price snapshots, idempotent placement, escrowed
  online payment through the `marketplace.order` payable, auto-completion, cash on pickup and free
  items.
- Disputes resolved by mediators (refund, partial refund, release) with conflict-of-interest
  checks; reviews with replies and moderated ratings.
- Moderatable listings (removal refunds buyers) and reviews, private and erasable delivery details,
  export, purge and retention.

## university-creator 0.1.0 — initial release

### Added

- Creator profiles that follow the account's privacy settings and blocks, with seeded
  categories, discovery and a verified badge on the public profile.
- Verification requests reviewed by someone else, decisions audited, and revocation.
- Linked accounts behind `SocialProvider` adapters (`ManualProvider`, `YouTubeProvider`):
  bio-challenge or reviewer-confirmed ownership, trusted-only `verified_reach`, one creator per
  verified account (database constraint), follower snapshots and scheduled syncing.
- Media kits with validated audience, rates and highlights; public, unlisted (revocable token)
  and private visibility; live platform stats.
- Sponsorship campaigns: applications, invitations, shortlisting, slots (database check),
  requirements, agreed fees, deliverables with review, and #ad disclosure confirmation; a
  moderatable `creator.campaign` adapter with an explicit policy.
- Privacy-preserving analytics: daily aggregates from ids-only events, de-duplicated views
  without viewer records, retention, export and purge.

## university-events 0.1.0 — initial release

### Added

- Events hosted by people or scopes (institution, community …) with public, unlisted and
  members-only visibility; drafts, publishing, cancellation and moderation-hidden states.
- Registration that can't be oversold (row locks plus database check constraints), a unique
  registration per person, FIFO waitlists with auto-promotion, approvals and registration windows.
- Ticket types with quantities and sales windows. Optional paid tickets use seat holds,
  `events.registration.payment_required`, an idempotent `confirm_payment()` and hold expiry.
- HMAC-derived ticket codes (never stored, rotation-safe) for check-in by door staff; online links
  only for confirmed attendees.
- Organizer teams (owner, organizer, check-in) granted through `permissions.implicit_grants`;
  events are permission children of their host scope; the `events_manager` role.
- Sessions with speakers, reusable venues, cover images, RFC 5545 calendar files, a
  CSV-injection-safe attendee export, and attendee notices (cancelled, rescheduled, reminders).
- A moderatable `events.event` adapter with an explicit policy (host-scope moderators; hide,
  restore, remove); spam screening; content-creation restrictions; audit; export, purge and
  retention.

## university-notifications 0.1.0 — initial release

### Added

- Event-driven notifications for social, moderation, appeals, institution, community and security
  events; no producer imports the module. Nothing is sent about anonymous content.
- Read-time rendering (no content copies), permission-checked target labels, block-aware
  creation, actor-less system notices, aggregation and deduplication through unread group keys.
- Per-category, per-channel preferences on Core's notification settings; mandatory categories;
  quiet hours in the person's time zone; daily/weekly email digests.
- Email, push (FCM HTTP v1, Expo, null) and SMS channels; atomically claimed deliveries with
  exponential-backoff retries, hourly push cap, invalid-token device disabling.
- Feed, counts, read/unread/read-all/seen, categories and device APIs; export, purge, retention
  policies and a delivery health check; `send_notification_digests` command.

## university-community 0.1.0 — initial release

### Added

- Public, restricted and private communities with configurable kinds, rules, parent audiences,
  "members of the audience only", and official recognition by parent-scope managers.
- Posting and commenting policies (members / moderators / admins / disabled), enforced across
  social and anonymous through `audience.can_post`.
- A strict role hierarchy with exactly one owner, explicit ownership transfer, and rank-checked
  role changes, removals and bans.
- Join requests, direct invitations, hashed invite links with expiry and use limits.
- Communities as audiences (`scopes.memberships`) and permission scopes with implicit role grants,
  plus a parent resolver to linked audiences.
- A `community.community` adapter routing reports to the parent scope; profile, export and purge
  hooks (ownership succession); retention for expired invite links.

## university-moderation 0.1.0 — initial release

### Added

- Reports with configurable, severity-weighted reasons; one open case per item with evidence
  snapshots and scope ancestry for scoped queues.
- Actions: dismiss, warn, hide, remove, restore, restrict (cross-module, time-boxed), suspend and
  ban. Audited, with a conflict-of-interest guard and permission layering for account sanctions.
- Appeals with four-eyes review and automatic reversal; explainable automated rules limited to
  reversible actions.
- Anonymous-content support: no stored author, a sanction permission gate with audit, and appeals
  by proof of authorship.
- A `users.user` content adapter (account reports), export, purge and retention.

## university-anonymous 0.1.0 — initial release

### Added

- Anonymous posts and comments scoped to audiences, with per-thread pseudonyms and OP labels,
  reactions, and per-viewer hiding.
- Authorship stored only as per-item keyed owner tokens plus Fernet-encrypted identities (key
  rotation); random UUIDv4 ids and coarsened timestamps.
- Two-person identity reveal with justification, expiry and full auditing.
- Abuse gates (verified email, account age, audience membership), rate limits, spam screening,
  moderation adapters and sanctions.
- A mandatory leakage test suite (responses, moderation views, events, database, audit log,
  errors, exports, block oracle), mutation-tested.

## university-social 0.1.0 — initial release

### Added

- Posts with text, images, polls, hashtags (Unicode), mentions, links, optional location and edit
  history (`PostRevision`).
- Visibility `public`, `followers`, `private` and audience scopes, with a single SQL visibility
  selector mirrored in Python and cross-checked by tests; profile privacy integration.
- Two-level comments, reactions on posts and comments, reposts and quotes (public posts only),
  bookmarks.
- Social graph: follow with optional approval, block (enforced platform-wide through Core hooks),
  mute, restrict; mention policies; follower and following lists that respect protection and
  blocks.
- Pluggable feeds: home, explore and trending (engagement-velocity ranking).
- Anti-spam screening with review queue, audience-scoped moderation with auditing, service-level
  rate limits, retention for unattached media, data export and purge hooks.
- `integration_tests/`: Core + institution + social composed, including whole-platform OpenAPI
  validation.

## university-core 0.1.0 — initial release

### Added

- **Core**: UUID base models (`UUIDModel`, `TimeStampedModel`, `BaseModel`, `SoftDeleteModel`),
  configurable UUIDv4/v7 identifiers, namespaced `UNIVERSITY` settings with deep-merged defaults,
  the module registry (`UniversityAppConfig`) and entry-point plugins, the event bus
  (dispatch-on-commit, async handlers), hooks, a task abstraction (immediate, Celery,
  `django.tasks`), provider adapters (email; SMS for Termii, Twilio and Africa's Talking; search;
  anti-spam), distributed rate limiting, idempotency keys, signed and de-duplicated webhooks,
  secure upload validation, health and readiness endpoints, structured redacted logging, request
  IDs, API security headers, system checks including `--deploy` rules, a retention framework,
  and the `university_modules` and `university_purge` commands.
- **API infrastructure**: versioned URL composition from installed modules, a consistent error
  envelope, cursor and page-number pagination, global and scoped throttles, strict serializers,
  OpenAPI integration through optional drf-spectacular, and settings presets.
- **Users**: swappable `AbstractUniversityUser`, account statuses, enumeration-resistant
  registration (`verify_first`) or `open` mode, email/phone verification, password
  reset/change, email change, privacy/notification/security settings, consent records, data
  export, soft deletion with anonymisation after a grace period, and staff status actions.
- **Security**: JWT access tokens bound to sessions and security stamps, opaque rotating refresh
  tokens with reuse detection, session management, scoped API keys, brute-force lockout,
  suspicious-login detection with email alerts, OTP, MFA, passwordless login, OIDC identity
  providers and account linking.
- **Permissions**: scoped RBAC with scope-hierarchy resolvers, system role synchronisation,
  privilege-escalation protection, cache invalidation, DRF permission classes and an API.
- **Audit**: append-only, HMAC-signed audit log with an optional hash chain, pluggable sinks,
  a verification command, an admin view, an auditor API and user activity history.

### Security

- Secrets (refresh tokens, API keys, OTPs, login identifiers) are stored only as keyed hashes,
  with support for HMAC key rotation.

## university-institution 0.1.0 — initial release

### Added

- Configurable institution types (seeded from settings), institutions as permission scopes,
  email domains, campuses, academic unit trees with College/Faculty/School/Department proxies,
  programmes, levels, academic sessions and semesters.
- Multi-institution memberships with configurable roles, primary membership, study details and
  the full lifecycle (pending, verified, rejected, suspended, revoked, left).
- Pluggable verification providers: institutional email + OTP, student/staff identifier review,
  document review with private storage, manual review, and auto-approve for development.
- Institution administrator, verifier and platform-manager roles, scoped permissions, and a
  campus → institution scope resolver.
- Profile affiliations hook (respects privacy), data export and purge hooks, a retention policy
  for verification documents, and the `university_import_institutions` command (JSON/CSV,
  idempotent).
