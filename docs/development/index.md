# Development

## Repository layout

```text
University/
├── packages/
│   ├── university-core/          # Level 1 distribution
│   │   ├── src/university/{core,users,security,permissions,audit}/
│   │   └── tests/                # isolated settings + a sample plugin module (tests/testapp)
│   └── university-institution/   # Level 2 distribution
│       ├── src/university/institution/
│       └── tests/
├── templates/module/             # scaffold used by scripts/new_module.py
├── scripts/                      # test_all.py, new_module.py
├── example_project/              # how a consumer composes the platform
├── loadtests/                    # Locust scenarios
├── docs/
├── .github/                      # CI, security scanning, trusted-publishing release
├── pyproject.toml                # workspace tooling config (ruff, mypy, coverage, bandit)
└── noxfile.py                    # lint / typecheck / tests matrix / security / build
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e "packages/university-core[test]" -e "packages/university-institution[test]"
pip install ruff nox
```

## Everyday commands

```bash
python scripts/test_all.py                    # every package, isolated
python scripts/test_all.py institution -- -x  # one package, extra pytest args
ruff check . && ruff format .
nox -s lint tests
UNIVERSITY_TEST_DB=postgres python scripts/test_all.py   # uses PG* environment variables
```

Run Django commands for a package from its directory:

```bash
cd packages/university-institution
DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=. python -m django makemigrations university_institution
DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=. python -m django spectacular --validate --file /tmp/schema.yml
```

## Testing utilities

`university.core.testing` provides:

- `build_test_settings(installed_apps=[...], root_urlconf=...)`: fast and isolated (SQLite in
  memory, MD5 hasher, local-memory cache, locmem email, events that raise), with PostgreSQL
  available through `UNIVERSITY_TEST_DB=postgres`;
- fixtures: `api_client`, `user`, `other_user`, `staff_user`, `superuser`, `auth_client(user)` and
  `outbox`;
- `create_user()` and `authenticate(client, user)`;
- an autouse fixture that runs `transaction.on_commit` callbacks immediately in ordinary tests (use
  `@pytest.mark.django_db(transaction=True)` to test real commit semantics).

## Migrations

Each app owns its migrations. Never edit a released migration destructively; add a new one. CI
runs `makemigrations --check` for every package. Initial migrations are generated per app in
dependency order (`users`, `audit`, `core`, `security`, `permissions`).

## Code standards

PEP 8 via ruff (line length 120), type hints throughout, docstrings on public APIs, and small
functions. Avoid god classes, `utils.py` dumping grounds, hidden global state and magic strings:
constants live in `constants.py`, `events.py` and `actions.py`.
