# Architecture

> Everything essential belongs in Core. Everything optional belongs in a standalone module.

## The two-level structure

```text
┌──────────────────────────── Level 1: university-core ─────────────────────────────┐
│                                                                                    │
│  university.core         settings · registry · events · hooks · tasks · providers   │
│                          base models · API infra · health · idempotency · webhooks  │
│  university.audit        append-only signed audit log                               │
│  university.users        custom user · accounts · preferences · privacy             │
│  university.security     tokens · sessions · API keys · OTP · MFA · OIDC            │
│  university.permissions  scoped RBAC                                                │
└─────────────────────────────────────────┬──────────────────────────────────────────┘
                                          │  extension points only
┌──────────────────────────── Level 2: feature packages ────────────────────────────┐
│ university-institution · university-social · university-anonymous ·               │
│ university-moderation · university-community · university-notifications · …       │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Why two levels and not one package per feature in Core?** The five Core apps change together
and are needed together, so shipping them as one distribution avoids version-skew problems.
Features vary between deployments, so each is its own distribution with its own version and
release cadence. This gives the benefits of a modular platform without the maintenance cost of
dozens of interdependent micro-packages.

### Namespace packaging

Every distribution installs into the shared `university` namespace (PEP 420). No distribution
ships `university/__init__.py`. Imports therefore look the same whichever packages are installed:

```python
from university.core.events import publish
from university.institution.services import request_membership  # only if installed
```

### Dependency rules

- Level-two modules depend on **Core only**: `dependencies = ["university-core>=0.1,<0.2"]`.
- If a module truly needs another module, it declares it in `module_requires` and the dependency
  graph must stay **acyclic**. The `university.E001` check reports missing requirements.
- Shared behaviour goes **down** into Core (as an abstraction, hook or event), never sideways
  between modules.
- Within Core the graph is `core ← audit ← permissions ← users ← security`. `users` uses
  `security` lazily for credential revocation, which is allowed because they ship together.

## Layers inside every app

```text
HTTP ──► View ──► Serializer ──► Service ──► Selector ──► Model / ORM
           │          │              │            │
     HTTP only   validation &    mutations,    reads &
                 representation  authorisation, visibility
                                 audit, events,
                                 transactions
```

| Layer | Responsibility | Never |
| --- | --- | --- |
| View | Parse the request, call one service or selector, render the response | Contain business rules |
| Serializer | Validate input; represent output; list fields explicitly | Write to the DB, use `__all__` |
| Service | Mutations; `authorize()`; invariants; `transaction.atomic`; audit; events | Trust client-supplied ownership, ids or roles |
| Selector | Queries; visibility, privacy and tenant scoping; whitelisted filters | Mutate |
| Model | Persistence, constraints, simple invariants | Call services |

Authorisation lives in services, so it holds for every entry point: API, admin actions,
management commands, tasks and other modules.

## The module contract

A module is a Django app whose `AppConfig` subclasses `UniversityAppConfig`:

```python
class InstitutionConfig(UniversityAppConfig):
    name = "university.institution"
    label = "university_institution"
    module_name = "institution"
    module_version = __version__
    module_requires = ("core", "users", "security", "permissions", "audit")
    settings_namespace = "INSTITUTION"
    api_urlconfs = {"v1": "university.institution.api.v1.urls"}

    def get_permissions(self): ...  # PermissionDef(...)
    def get_roles(self): ...  # RoleDef(...) — synced on migrate
    def get_scope_types(self): ...  # ScopeTypeDef(...) with parent resolvers
    def get_health_checks(self): ...  # HealthCheck(...)
    def get_retention_policies(self): ...  # RetentionPolicy(...)
    def get_throttle_rates(self): ...  # {"institution_join": "10/day"}
    def register_event_handlers(self, bus): ...
    def register_hooks(self, hooks): ...
```

The **registry** (`university.core.registry`) discovers these configs and aggregates what they
contribute. It also exposes `registry.get(name)`, `registry.is_installed(name)` and
`registry.require(name)`, which fail gracefully when an optional module is absent. Lightweight
plugins that need no models can register through the `university.plugins` entry-point group.

## Communication between modules

| Mechanism | Use for | Example |
| --- | --- | --- |
| **Events** (`university.core.events`) | Reacting to something that happened, asynchronously or after commit | `institution.joined` → a community module adds the user to the institution community |
| **Hooks** (`university.core.hooks`) | Taking part in a decision or a result while it is computed | social vetoes `users.can_view_profile` when the viewer is blocked; each module adds a section to `users.export_data` |
| **Permission scopes** | Authorisation across boundaries | campus scope resolves to its institution, so institution admins manage campuses |
| **Content adapters** | Cross-cutting modules naming, permission-checking or acting on any module's content | notifications name an institution through `get_adapter("institution.institution")`; moderation hides a `social.post` through `get_moderatable_adapter("social.post")`. Moderation is opt-in per adapter (`moderatable = True`); registering an adapter never makes content reportable |
| **Payable adapters** (`university.core.payables`) | Selling something without depending on payments | events sells `events.registration`; payments resolves it by purpose, takes the money and calls `on_paid`; escrow release and refunds travel as `payments.release.requested` / `payments.refund.requested` events |
| **Media library** (`university.core.media`) | Using stored media without depending on its module | podcasts attach an uploaded audio file by id, check it's processed, and redirect listeners to `library.url(id, variant="mp3")`; exactly one module (university-media) provides the library |
| **Providers** | Swappable external capabilities | SMS, email, search, anti-spam, verification, identity providers |

Event rules: names are lowercase dotted (`<domain>.<entity>.<verb>`), payloads are JSON
containing identifiers only (never secrets, never the identity behind anonymous content), and
handlers run after commit and are isolated from the publisher.

Core hooks: `users.can_view_profile`, `users.can_interact`, `users.public_profile`,
`users.export_data`, `users.purge`, `permissions.implicit_grants`, `permissions.implicit_scopes`,
`scopes.memberships`, `content.trending_scores` (trending scores for feeds), `audience.can_post` (audience posting policies, e.g. moderators-only
communities) and
`content.can_create` (moderation restrictions apply to every content module).

**Audiences.** `scopes.memberships` lets membership modules (institution, campus, community) declare
which audience scopes a user belongs to. Content modules call
`university.core.audiences.member_scopes(user)`. For example, social shows institution-only posts to
verified members of that institution without importing the institution module.

## Data design

- **UUID primary keys** everywhere (v4 by default, v7 optional). No integer ids are exposed.
- **Soft deletion**: `SoftDeleteModel.objects` hides deleted rows and `all_objects` includes them.
  Related-object access still resolves deleted rows, which preserves referential integrity.
- **Constraints over code**: uniqueness, "one current session", "one open membership per role",
  "one account per student number" and similar rules are enforced with database constraints
  (partial unique constraints where needed), so concurrent requests can't break them.
- **Atomic multi-step mutations** use `transaction.atomic`. Compare-and-set updates handle
  single-use items such as refresh tokens and OTPs.
- **Deliberate indexes** on access patterns (owner + created_at, status, scope).

## Scalability model

University is designed for horizontal scale. It doesn't claim unlimited capacity:

- **Stateless app servers**: no process-local state is relied on for correctness. Rate limits,
  lockouts and permission caches live in the shared cache.
- **PostgreSQL** with constraints and indexes. Read replicas and partitioning become relevant at
  the largest tiers.
- **Redis** for cache and throttling, **object storage** for media, and **Celery** for anything
  slow (email, SMS, media processing, indexing).
- The limits are set by infrastructure (database, cache, bandwidth). See
  [deployment](../deployment/index.md#scaling) for the load-testing approach and the scaling
  tiers.
