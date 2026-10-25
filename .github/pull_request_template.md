## What and why

<!-- What does this change do, and why is it needed? -->

## Checklist

- [ ] Business logic lives in services/selectors, not views or serializers
- [ ] Serializers list fields explicitly (no `__all__`, no `exclude`)
- [ ] Every mutation is authorised server-side (`authorize(...)`) and audited where sensitive
- [ ] Object lookups are scoped to the caller/tenant (no IDOR/BOLA)
- [ ] Tests added, including security tests for new endpoints
- [ ] Migrations included and checked (`makemigrations --check`)
- [ ] No secrets, tokens or personal data in logs, events or audit metadata
- [ ] Docs and CHANGELOG updated
- [ ] No new cross-module dependency (use events/hooks) — or it is justified below
