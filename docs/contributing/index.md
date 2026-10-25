# Contributing

## Workflow

1. Open an issue describing the problem or proposal. New modules or cross-module behaviour need a
   short design note (models, services, events, hooks, permissions, privacy impact).
2. Fork or branch from `main`.
3. Implement following [the architecture](../architecture/index.md) and
   [module guide](../modules/writing-a-module.md).
4. Add tests (functional and security), docs and a `CHANGELOG.md` entry.
5. Run `ruff check .`, `ruff format --check .` and `python scripts/test_all.py`.
6. Open a pull request and complete the checklist in the template.

## Review criteria

- **Security**: authorisation in services; tenant and owner scoping; no enumeration; no secrets or
  PII in logs, events or audit metadata; abuse controls on anything user-generated.
- **Modularity**: no imports of another module's internals; dependencies acyclic; Core changes only
  when an abstraction is genuinely shared.
- **Compatibility**: public APIs (`services`, `selectors`, models, settings, events, URLs) follow
  SemVer. Breaking changes need a major version, and deprecations need a replacement and a removal
  version.
- **Data**: constraints enforce invariants; migrations are reversible where practical; indexes match
  access patterns.
- **Quality**: typed, documented, small units, no dead code.

## Releasing (maintainers)

1. Bump `__version__` in the package's `__init__.py` and move the `CHANGELOG.md` entries under
   the new version.
2. Tag `university-<package>-v<version>` (for example `university-core-v0.2.0`).
3. The release workflow tests, builds, validates and publishes through PyPI trusted publishing.

## Code of conduct

Be respectful, inclusive and constructive. Harassment and discrimination are not tolerated.
Maintainers may remove contributions or contributors that violate this standard.
