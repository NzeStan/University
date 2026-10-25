# Contributing to University

Thank you for helping build infrastructure for African campus communities.
The full guide is in [docs/contributing](docs/contributing/index.md); the essentials:

1. **Discuss first** for anything larger than a bug fix: open an issue describing the problem
   and the proposed design (especially new modules or cross-module behaviour).
2. **Branch** from `main`; keep pull requests focused.
3. **Follow the architecture**: views → serializers → services → selectors → models. Mutations
   authorise, audit and publish events in services. Modules communicate through events, hooks
   and scopes, never through another module's internals.
4. **Test**: every change needs tests, and every new endpoint needs security tests (IDOR/BOLA,
   mass assignment, permission boundaries).
5. **Check locally**:

   ```bash
   ruff check . && ruff format --check .
   python scripts/test_all.py
   ```

6. **Document**: update the relevant docs and add a `CHANGELOG.md` entry.

Security issues: please follow [SECURITY.md](SECURITY.md); do not open public issues.
