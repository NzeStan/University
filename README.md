# University

**A secure, modular backend platform for African campus ecosystems — built on Django REST Framework.**

University powers digital campus products that connect students, graduates, staff, institutions,
creators and communities. It is Nigeria-first and Africa-ready: nothing in the core assumes a
country, an institution or a business model.

It is a **platform**, not an application. You install the foundation, then add only the features
you need. Each feature is a separately installable package that plugs in through stable extension
points.

```bash
pip install university-core                # the foundation
pip install university-institution         # + institutions, campuses, verified memberships
pip install university-social              # + posts, comments, reactions, feeds, social graph
pip install university-moderation          # + reports, cases, actions, appeals, automated rules
pip install university-anonymous           # + anonymous posts with encrypted, two-person-reveal accountability
pip install university-community           # + communities: roles, privacy, invitations, delegated moderation
pip install university-notifications       # + in-app, email, push (FCM/Expo) and SMS notifications
pip install university-events              # + events, tickets, waitlists, schedules, venues, check-in
pip install university-creator             # + creator profiles, verification, media kits, sponsorships, analytics
pip install university-payments            # + Paystack / Flutterwave / Stripe, escrow ledger, refunds, payouts
pip install university-marketplace         # + listings, inventory, orders with escrow, disputes, reviews
pip install university-media              # + secure uploads, object storage, async processing, signed streaming
pip install university-podcast            # + shows, episodes, guests, transcripts, clips, RSS, listening analytics
pip install university-analytics          # + privacy-conscious aggregates, active users, institution dashboards
pip install university-trending           # + configurable trending (velocity, engagement, recency)
pip install university-search             # + permission-aware search (PostgreSQL FTS, OpenSearch/Elasticsearch)
```

---

## Contents

- [Why University](#why-university)
- [Architecture: the two-level structure](#architecture-the-two-level-structure)
- [What's included](#whats-included)
- [Quick start](#quick-start)
- [Security](#security)
- [Configuration](#configuration)
- [API](#api)
- [Writing a module](#writing-a-module)
- [Development and testing](#development-and-testing)
- [Packaging and releases](#packaging-and-releases)
- [Roadmap](#roadmap)
- [Documentation](#documentation)

---

## Why University

Campus platforms across Africa keep rebuilding the same foundations: accounts, verification,
institutions, moderation, notifications. They often rebuild them insecurely, or as monoliths that
can't evolve. University provides those foundations once, done properly:

- **Security-first**: OWASP-aligned controls, tested against IDOR/BOLA, mass assignment, token
  forgery, enumeration and privilege escalation.
- **Modular**: install only what you use; modules never import each other's internals.
- **Scalable by design**: stateless app servers, shared cache, task queues, UUID keys and deliberate
  indexes. Capacity is set by infrastructure, not by a ceiling in the code.
- **Configurable rather than forked**: settings, providers, hooks, events and swappable
  serializers.

## Architecture: the two-level structure

```text
Level 1  ┌────────────────────────── university-core ──────────────────────────┐
         │ core · users · security · permissions · audit                        │
         │ settings · registry · events · hooks · tasks · providers · API infra │
         └──────────────────────────────────┬───────────────────────────────────┘
                                            │ registry · events · hooks · scopes
Level 2  ┌──────────────┬──────────────┬─────┴────────┬──────────────┬──────────┐
         │ institution ✅│ social ✅     │ anonymous ✅ │ community ✅ │ events … │
         └──────────────┴──────────────┴──────────────┴──────────────┴──────────┘
```

- **Level 1, `university-core`**: one distribution containing the five Django apps nearly every
  installation needs. They are versioned and released together.
- **Level 2, feature packages**: each is an independent distribution (`university-<feature>`) that
  depends only on Core. They share the `university.*` import namespace (PEP 420), so imports look
  the same whichever packages are installed.

Modules talk to each other through **events**, **hooks** and **permission scopes**, never through
direct imports of another module's internals. Dependencies form a directed graph with no cycles.
See [docs/architecture](docs/architecture/index.md).

Every module follows the same layered pattern:

```text
View (HTTP only) → Serializer (validation/representation) → Service (mutations, authorisation,
audit, events, transactions) → Selector (reads, visibility rules) → Models (persistence, invariants)
```

## What's included

### `university-core` (Level 1)

| App | Highlights |
| --- | --- |
| `university.core` | UUID base models, soft deletion, namespaced settings, module registry, plugin entry points, event bus, hooks, task abstraction (Celery / django.tasks / immediate), provider adapters (email, SMS: Termii, Twilio, Africa's Talking; search; anti-spam), distributed rate limiting, idempotency keys, signed webhook handling, secure uploads, health checks, structured redacted logging, request IDs, system checks, retention framework |
| `university.users` | Swappable custom user (`AbstractUniversityUser`), email/handle/verified-phone login, account statuses, enumeration-resistant registration, email/phone verification, password reset/change, email change, privacy/notification/security settings, consent records, data export, soft deletion with anonymisation |
| `university.security` | Pluggable access tokens (JWT by default), opaque rotating refresh tokens with reuse detection, device/session management, API keys limited to permission scopes, brute-force lockout, suspicious-login detection and alerts, OTP, MFA, passwordless login, OAuth/OIDC providers |
| `university.permissions` | Scoped RBAC (platform → institution → campus → …), code-declared permissions, system roles, protection against privilege escalation, cache invalidation, DRF permission classes |
| `university.audit` | Append-only, HMAC-signed audit log with optional hash chain, pluggable sinks, verification command, user activity history |

### `university-institution` (Level 2)

Configurable institution types, institutions as tenant boundaries, email domains, campuses, a
flexible academic tree (college / faculty / school / department / …), programmes, levels, sessions
and semesters, multi-institution memberships with configurable roles, and **pluggable
verification**. Four methods are built in: institutional email + OTP, student/staff number review,
document review and manual review. Identifiers are stored only as keyed hashes. See
[docs/modules/institution.md](docs/modules/institution.md).

### `university-social` (Level 2)

Posts with images, polls, hashtags, mentions and edit history; per-post visibility (`public`,
`followers`, `private`, or an **audience** such as an institution or campus, resolved through Core
hooks so social never imports the institution module); two-level comments, reactions, reposts and
quotes, bookmarks; follow with optional approval, plus block, mute and restrict, all enforced
server-side; pluggable feeds (home, explore, trending by engagement velocity); anti-spam review;
and moderation scoped to the content's audience. See [docs/modules/social.md](docs/modules/social.md).

### `university-moderation` and `university-anonymous` (Level 2)

**Moderation** handles any content type through Core content adapters: reports with configurable
severities, prioritised queues scoped to each moderator's authority, actions from hide to ban (all
audited, with a conflict-of-interest guard), cross-module restrictions, four-eyes appeals, and
explainable automated rules that only take reversible actions. **Anonymous** posting is unlinkable
to the public and accountable to the platform: there is no author column, ownership is proven by
per-item keyed tokens, identities are stored Fernet-encrypted, reveals need two people and are
audited, and a mutation-tested leakage suite guards it all. See
[docs/modules/moderation.md](docs/modules/moderation.md) and
[docs/modules/anonymous.md](docs/modules/anonymous.md).

### `university-community` (Level 2)

Public, restricted and private communities (interest, institution, department, club, creator …).
They have a strict owner > admin > moderator > member hierarchy, invitations and hashed invite
links, and optional "members of this institution only" and official recognition. Communities are
audiences and permission scopes, so community-only posts, anonymous community boards and
community-scoped moderation queues work automatically through Core hooks. See
[docs/modules/community.md](docs/modules/community.md).

### `university-notifications` (Level 2)

Event-driven in-app, email, push (FCM HTTP v1, Expo) and SMS notifications. Mentions, comments,
reactions, follows, moderation decisions, appeals, institution verification, community invitations
and security alerts become notifications without those modules importing it. Titles are rendered
at read time (no content copies), blocks are respected, moderators are never named, and anonymous
authors are never notified. Per-category preferences, quiet hours in each person's time zone,
aggregation ("Ada and 4 more…"), daily/weekly digests, and exactly-once delivery with retries. See
[docs/modules/notifications.md](docs/modules/notifications.md).

### `university-events` (Level 2)

Events hosted by people, institutions or communities, including members-only events. Covers
discovery, registration, capacity that can't be oversold (row locks plus database constraints),
FIFO waitlists with auto-promotion, approvals, ticket types, optional paid tickets through an
ids-only payments contract, schedules, venues, organizer teams, HMAC ticket codes for door
check-in, calendar files, reminders and cancellation notices. Events opt in to moderation with an
explicit policy: reports go to the host's moderators. See [docs/modules/events.md](docs/modules/events.md).

### `university-creator` (Level 2)

Creator profiles that follow account privacy, verification by reviewers, and linked social accounts
behind `SocialProvider` adapters (bio-challenge ownership, confirmed reach only, no
impersonation). Also media kits with revocable share links, and sponsorship campaigns with slots,
requirements, deliverables and #ad disclosure. Analytics are privacy-preserving daily aggregates.
See [docs/modules/creator.md](docs/modules/creator.md).

### `university-payments` and `university-marketplace` (Level 2)

Payments sit behind a `PaymentProvider` protocol (Paystack, Flutterwave and Stripe ship). Every
payment is re-verified with the provider, and webhooks are signed and de-duplicated. A
double-entry ledger holds escrow for sellers and creators, with automatic refunds when fulfilment
fails, and payouts processed with four-eyes checks. Modules sell through Core's **payable
adapters**, so the marketplace (orders), events (tickets) and creator (sponsorship fees) never
import payments. The marketplace adds listings with stock that can't oversell, campus-only
listings, escrowed orders, mediated disputes, cash on pickup and reviews. See
[docs/modules/payments.md](docs/modules/payments.md) and
[docs/modules/marketplace.md](docs/modules/marketplace.md).

### `university-media` and `university-podcast` (Level 2)

Media uploads are checked by content signature against per-kind allow-lists, with quotas,
duration and dimension limits, and SHA-256 hashes. Files go to private object storage (with
optional presigned direct uploads) and are processed asynchronously with sandboxed FFmpeg (MP3,
720p MP4, posters, clips). They're served through signed, expiring links with Range support, and
all of this is exposed as Core's **media library**. Podcasts add shows hosted by people or scopes,
ranked teams, episodes that wait for processed media, scheduling, consent-based guest links,
sanitised transcripts with optional AI transcription, clips, RSS with iTunes and Podcasting 2.0
tags, privacy-preserving listening analytics, and moderation routed to the host. See
[docs/modules/media.md](docs/modules/media.md) and [docs/modules/podcast.md](docs/modules/podcast.md).

### `university-analytics`, `university-trending` and `university-search` (Level 2)

- **Analytics** keeps daily aggregates only (no raw events, no user ids). Active users are counted
  with expiring keyed hashes, views are recorded only for content the viewer may see, and
  institution dashboards suppress small groups. Warehouse sinks receive pseudonyms that rotate
  monthly.
- **Trending** scores weighted engagement, velocity and recency, never total likes. Repeat signals
  are deduplicated, items need several distinct people, lists cap items per author, every listed
  item is checked for the viewer, and the algorithm is pluggable. It powers social's trending feed
  through a Core hook.
- **Search** offers PostgreSQL full-text and OpenSearch/Elasticsearch backends behind Core's
  abstraction, indexing through content adapters, and a per-viewer check on every result. People
  search is enumeration-resistant: never by email or phone.

See [docs/modules/analytics.md](docs/modules/analytics.md),
[docs/modules/trending.md](docs/modules/trending.md) and [docs/modules/search.md](docs/modules/search.md).

## Quick start

```bash
pip install "university-core[postgres,redis,celery,openapi,argon2]" university-institution
```

```python
# settings.py
from university.core import CORE_APPS
from university.core.settings import rest_framework_settings, recommended_middleware

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "rest_framework",
    "drf_spectacular",  # optional: OpenAPI docs
    *CORE_APPS,  # Level 1
    "university.institution",  # Level 2 — add only what you need
]
MIDDLEWARE = recommended_middleware()
REST_FRAMEWORK = rest_framework_settings()
AUTH_USER_MODEL = "university_users.User"
AUTHENTICATION_BACKENDS = ["university.users.backends.UniversityAuthBackend"]

UNIVERSITY = {
    "AUTH": {"JWT": {"SIGNING_KEY": env("JWT_SIGNING_KEY")}},
    "SECURITY": {"HMAC_KEY": env("UNIVERSITY_HMAC_KEY")},
}
```

```python
# urls.py
urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("university.core.urls")),  # /health/, /api/v1/…, /api/docs/
]
```

```bash
python manage.py migrate
python manage.py university_modules          # what's installed
python manage.py check --deploy              # University production checks included
```

A complete, runnable composition (Docker Compose with PostgreSQL, Redis, Celery worker and beat)
is in [`example_project/`](example_project/README.md).

## Security

Every protection below is implemented **and covered by tests**:

- **Authentication**: short-lived access tokens with a pinned algorithm (no `alg=none`, no algorithm
  confusion), bound to a session and to a security stamp. Refresh tokens are opaque, stored as
  HMACs and rotated on every use; replaying one revokes the whole session.
- **Credentials**: Django's password hashers (Argon2 recommended) and validators. Lockout counters
  on identifier+IP, identifier and IP. Responses take the same time whether or not the account
  exists. MFA by OTP is available.
- **Authorisation**: enforced in services as well as views. Scoped roles. Object lookups are
  confined to the caller or tenant (IDOR/BOLA). Users can't grant permissions they don't hold.
- **No enumeration**: registration, password reset, email change, passwordless login and profile
  lookups give the same response whether or not an account exists.
- **Mass assignment**: `StrictModelSerializer` refuses `__all__` and `exclude` at import time.
- **Data protection**: tokens, API keys, OTPs, login identifiers and student numbers are stored as
  keyed hashes, and secrets are redacted from logs.
- **Uploads**: files are checked by their content signature, not the declared type. Executables
  and active content are blocked, stored names are random, and private storage is separate.
- **Integrity**: the audit log is append-only and HMAC-signed, inbound webhooks are signed and
  de-duplicated, and unsafe requests can use idempotency keys.
- **Platform**: a consistent error envelope that never leaks internals, request IDs, hardened API
  headers, distributed throttling, and `check --deploy` rules for CORS, cache, keys, tasks, SMS
  and storage.

Read [SECURITY.md](SECURITY.md) for the disclosure policy and
[docs/security](docs/security/index.md) for the threat model and control mapping.

## Configuration

Everything lives in one namespaced setting with documented defaults. You only override what you
need:

```python
UNIVERSITY = {
    "AUTH": {"JWT": {"ACCESS_TOKEN_LIFETIME_SECONDS": 300}, "MFA": {"ENABLED": True}},
    "USERS": {"REGISTRATION_MODE": "verify_first"},
    "THROTTLE_RATES": {"login": "10/min"},
    "PROVIDERS": {
        "SMS": "university.core.providers.sms.TermiiSMSProvider",
        "SMS_OPTIONS": {"api_key": env("TERMII_KEY"), "sender_id": "Campus"},
    },
    "TASKS": {"BACKEND": "university.core.tasks.CeleryTaskBackend"},
    "INSTITUTION": {"ALLOW_MULTIPLE_INSTITUTIONS": True},
}
```

Full reference: [docs/configuration](docs/configuration/index.md).

## API

- Versioned from day one: `/api/v1/…` (namespace versioning; `/api/v2/` can run alongside it).
- One error format everywhere:
  `{"error": {"code", "message", "details", "request_id"}}`.
- Cursor pagination for feeds, page-number pagination for admin lists, whitelisted filters only.
- OpenAPI 3 schema at `/api/schema/` and Swagger UI at `/api/docs/` (validated in CI).

Endpoint catalogue and conventions: [docs/api](docs/api/index.md).

## Writing a module

```bash
python scripts/new_module.py social --description "Posts, comments, reactions and follows."
```

This generates `packages/university-social/` with a working model, service, selector, API, admin,
event handler, permissions and tests that already follow every convention. Adding it to
`INSTALLED_APPS` mounts its API, registers its permissions and connects its handlers. Core never
changes. Guide: [docs/modules/writing-a-module.md](docs/modules/writing-a-module.md).

## Development and testing

```bash
python -m venv .venv && source .venv/bin/activate
pip install $(printf -- '-e %s[test] ' packages/*/)   # one call, so siblings resolve locally
python scripts/test_all.py          # every package, each with its own isolated settings
ruff check . && ruff format --check .
nox                                 # lint + Python × Django matrix
```

Each package's tests run on their own against only Core plus that package, which proves the
modularity. `integration_tests/` then installs every package together and checks that they
compose (for example, verified institution members seeing institution-only posts). Tests use SQLite by default; set `UNIVERSITY_TEST_DB=postgres` to run against
PostgreSQL, as CI does.

## Packaging and releases

- Modern `pyproject.toml` packaging with Hatchling. Each package is versioned independently with
  [SemVer](https://semver.org/).
- Supported versions: Python 3.11–3.14; Django 5.2 LTS, 6.0, 6.1; DRF 3.15+.
- Optional extras keep dependencies minimal: `postgres`, `redis`, `celery`, `openapi`, `argon2`,
  `oidc`, `images`, `cors`.
- Releases use tags (`university-core-v0.1.0`) and PyPI **Trusted Publishing** (OIDC), so no
  long-lived tokens are stored.

## Roadmap

| Phase | Package(s) | Status |
| --- | --- | --- |
| 1. Foundation | `university-core` | ✅ Done |
| 2. Institution | `university-institution` | ✅ Done |
| 3. Social | `university-social` (posts, comments, reactions, follows, media, feeds) | ✅ Done |
| 4. Anonymous | `university-anonymous`, `university-moderation` | ✅ Done |
| 5. Communities | `university-community` | ✅ Done |
| 6. Notifications | `university-notifications` | ✅ Done |
| 7. Events | `university-events` | ✅ Done |
| 8. Creator | `university-creator` | ✅ Done |
| 9. Marketplace | `university-marketplace`, `university-payments` | ✅ Done |
| 10. Podcast | `university-podcast`, `university-media` | ✅ Done |
| 11. Analytics | `university-analytics`, `university-trending`, `university-search` | ✅ Done |

The planned module boundaries, events and extension points are described in
[docs/modules](docs/modules/index.md).

## Documentation

| Topic | |
| --- | --- |
| [Installation](docs/installation/index.md) | Requirements, extras, composing apps |
| [Configuration](docs/configuration/index.md) | Every setting and default |
| [Architecture](docs/architecture/index.md) | Two-level structure, layers, registry, events, hooks |
| [Authentication](docs/authentication/index.md) | Tokens, sessions, API keys, MFA, OIDC |
| [Security](docs/security/index.md) | Threat model, OWASP mapping, privacy and retention |
| [Modules](docs/modules/index.md) | Catalogue, institution module, writing a module |
| [API](docs/api/index.md) | Conventions, errors, pagination, versioning, endpoints |
| [Deployment](docs/deployment/index.md) | Production checklist, scaling, observability, load testing |
| [Development](docs/development/index.md) | Repository layout, tooling, testing |
| [Contributing](docs/contributing/index.md) | Workflow and standards |

## License

Open source under the MIT License (placeholder; the project owner may change it). See
[LICENSE](LICENSE).
