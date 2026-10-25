# Writing a University module

A module adds a capability without modifying Core. This guide uses the generator and then explains
each convention it follows.

## 1. Generate

```bash
python scripts/new_module.py events --description "Campus events, registration and tickets."
pip install -e packages/university-events
cd packages/university-events
DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=. python -m django makemigrations university_events
pytest
```

You get a passing test suite and this layout:

```text
packages/university-events/
├── pyproject.toml            # depends on university-core only
├── src/university/events/    # no src/university/__init__.py (namespace package)
│   ├── __init__.py           # __version__
│   ├── apps.py               # UniversityAppConfig: permissions, roles, routes, handlers …
│   ├── conf.py               # ModuleSettings("EVENTS", DEFAULTS)
│   ├── models.py             # BaseModel / SoftDeleteModel subclasses
│   ├── services.py           # mutations: authorize → validate → write → audit → publish
│   ├── selectors.py          # reads with visibility rules
│   ├── events.py             # event name constants
│   ├── handlers.py           # subscriptions to other events
│   ├── admin.py
│   ├── api/v1/{serializers,views,urls}.py
│   └── migrations/
└── tests/                    # own settings: Core + this module only
```

## 2. Declare what you contribute

```python
class EventsConfig(UniversityAppConfig):
    name = "university.events"
    label = "university_events"  # unique, prefixed
    module_name = "events"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "EVENTS"
    api_prefix = "events/"
    api_urlconfs = {"v1": "university.events.api.v1.urls"}

    def get_permissions(self):
        return [PermissionDef("events.manage", "Manage events.", scopes=("platform", "institution"))]

    def get_roles(self):
        return [RoleDef("event_organizer", "Event organiser", "institution", ("events.*",))]

    def get_throttle_rates(self):
        return {"event_registration": "30/hour"}

    def register_event_handlers(self, bus):
        bus.subscribe("user.deleted", cancel_registrations_of_deleted_user)
```

## 3. Follow the conventions

- **UUIDs**: inherit `BaseModel`. Never expose integer ids.
- **Explicit serializers**: inherit `StrictModelSerializer`. List fields, mark read-only fields,
  and never use `__all__` or `exclude`.
- **Services own mutations**: call `authorize(actor, "events.manage", Scope("institution", id))`.
  Derive ownership from the actor, wrap multi-step writes in `transaction.atomic`, write an audit
  entry for sensitive changes and `publish()` an event.
- **Selectors own reads**: apply visibility and tenant scoping there, and whitelist filters
  explicitly.
- **Scope object lookups**: `Model.objects.filter(pk=id, owner=request.user)` or
  `…, institution=institution`, and return 404 for anything outside the caller's reach.
- **Concurrency**: enforce uniqueness with database constraints (partial `UniqueConstraint`) and
  handle `IntegrityError` → `Conflict`.
- **Async work**: use `@task` plus `enqueue()`, with JSON arguments only (pass ids).
- **Integration through extension points**: events for reactions, hooks for decisions
  (`users.can_interact`, `users.export_data`, `users.purge`), scopes for authorisation.
  **Don't import another module's internals.**
- **Privacy**: contribute export and purge hooks for personal data you store, and declare
  retention policies.
- **Rate limits**: set `throttle_scope` on views and call `rate_limit()` in services for abusive
  actions.
- **OpenAPI names**: prefix serializer class names with your module (`EventTicketSerializer`, not
  `TicketSerializer`) and add your enums to `ENUM_NAME_OVERRIDES`. The integration suite validates
  the whole platform's schema with `--fail-on-warn`, so collisions fail CI.
- **Errors**: raise `university.core.exceptions.*`. The error envelope is applied automatically.
- **Docs**: add schema hints with `university.core.api.schema.extend_schema` (it's a no-op without
  drf-spectacular).

## 4. Test like Core does

Use the fixtures from `university.core.testing` (`user`, `other_user`, `superuser`, `auth_client`,
`outbox`). Each test suite must cover:

- the happy path, plus validation errors;
- **IDOR/BOLA**: another user or tenant gets a 404 and nothing changes;
- **permission boundaries**: no permission gives 403, wrong scope gives 403, correct scope succeeds;
- **mass assignment**: protected fields in the payload are ignored;
- events and audit entries for sensitive actions.

## 5. Release

Add a `CHANGELOG.md` entry and tag `university-events-v0.1.0`. The release workflow tests, builds
and publishes through trusted publishing.
