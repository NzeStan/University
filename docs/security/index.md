# Security

University is security-first: every control below is implemented in the code **and** covered by
a regression test (look for `@pytest.mark.security`).

## Threat model (summary)

| Asset | Threats | Primary controls |
| --- | --- | --- |
| Accounts and sessions | credential stuffing, brute force, token theft and replay, session fixation | lockout counters, pinned-algorithm JWTs, short access lifetime, rotating hashed refresh tokens with reuse detection, security stamps, MFA, login alerts |
| Personal data | enumeration, IDOR/BOLA, over-exposure, insider misuse | indistinguishable responses, object scoping in services, explicit serializers, privacy settings, scoped roles, audit log |
| Authorisation | privilege escalation, scope escape, mass assignment | permissions enforced in services, no-escalation rule, strict serializers, server-side ownership |
| Integrity | tampering, duplicate execution, forged webhooks | append-only HMAC-signed audit log, idempotency keys, signed and de-duplicated webhooks, DB constraints |
| Availability | request flooding, abusive clients | distributed global and scoped throttles, per-destination OTP caps, task offloading |
| Uploaded files | malware, stored XSS, path traversal | content-signature checks, blocked active content, random names, private storage |

## OWASP mapping

| Risk | How University addresses it | Where |
| --- | --- | --- |
| SQL injection | ORM only; filters are whitelisted and never passed as raw lookups | selectors (`ALLOWED_FILTERS`, explicit params) |
| XSS | JSON API with locked-down CSP and `nosniff`; text emails with autoescape where needed; uploads block HTML/SVG | `APISecurityHeadersMiddleware`, `uploads.is_dangerous` |
| CSRF | Session authentication enforces CSRF; token auth carries no ambient credentials; CSRF is never disabled globally | DRF `SessionAuthentication`, test `test_csrf_enforced_for_cookie_sessions` |
| SSRF | Outbound calls only to operator-configured HTTPS provider URLs, with timeouts and no redirects | `core/providers/http.py` |
| IDOR / BOLA | Object lookups filtered by owner or tenant in services; 404 for others' objects | e.g. `revoke_user_session`, `MyMembershipDetailView`, `resolve_references` |
| Privilege escalation | `authorize()` in services; granters must hold every permission they grant; API keys limited to their scopes; system roles immutable through the API | `permissions/services.py` |
| Mass assignment | `StrictModelSerializer` forbids `__all__`/`exclude`; services take explicit allowed fields | `core/api/serializers.py`, `apply_fields` |
| Broken authentication | See [authentication](../authentication/index.md) | `security/` |
| Enumeration | Registration, reset, email change, passwordless and profiles give the same response; timing equalised | users/security services |
| Replay | Single-use OTPs and refresh tokens (compare-and-set); webhook timestamps plus event-id de-duplication; idempotency keys | `otp.py`, `sessions.py`, `webhooks.py`, `idempotency.py` |
| Insecure deserialisation | JSON only; no pickle from clients; task payloads are JSON-validated; async handlers are allow-listed | `tasks.py`, `events.run_async_handler` |
| Path traversal | Generated storage names; extensions derived from content | `uuid_upload_to` |
| Sensitive data exposure | Keyed hashes for secrets and identifiers; redacted logs; masked evidence | `crypto.py`, `logging.py` |
| Security misconfiguration | `check --deploy` rules (CORS, cache, keys, task backend, SMS, storage) plus Django's own | `core/checks.py` |

## Anonymous content

See the [anonymous module's threat model](../modules/anonymous.md#threat-model). In short: there is
no author column, ownership is proven by per-item keyed tokens, identities are stored
Fernet-encrypted, reveals need two people and are audited, the audit log and events never link
authors to content, and a mutation-tested leakage suite enforces all of this in CI.

## Never trusted from clients

`user_id`, `institution_id`, roles, permissions, ownership, verification status, `Content-Type`
of uploads, `X-Forwarded-For` (unless `TRUSTED_PROXY_COUNT` is set) and `X-Request-ID` (unless
`TRUST_INCOMING_REQUEST_ID` is set). Ownership always comes from `request.user`, and tenant ids are
checked against the authenticated user's grants.

## Cryptography

No custom cryptography. Passwords use Django hashers (Argon2 recommended). Token and code storage
uses HMAC-SHA256 with keys derived per purpose from `SECURITY.HMAC_KEY`, and verification is
constant time. Keys can be rotated through `HMAC_KEY_FALLBACKS`: old hashes still verify, and
lookups use `keyed_hash_candidates`. Signed links use Django's `signing` module with salts and
expiry.

## Audit logging

`university.audit.services.record()` writes append-only entries containing the actor, action,
target, scope, IP, user agent, request id and redacted metadata. Updates and deletes are refused
by the model and the queryset, and only the retention job can purge old entries. Each entry
carries an HMAC (`entry_hash`) and optionally a hash chain (`AUDIT.HASH_CHAIN`). Verify with
`manage.py university_verify_audit [--chain]`. For stronger guarantees:

- grant the application's database role only `INSERT`/`SELECT` on `university_audit_auditlog`;
- add `university.audit.sinks.LoggingSink` and ship entries to WORM storage or a SIEM.

Audited events include login (success and failure), logout, lockouts, token reuse, session
revocation, password and email changes, MFA changes, API key creation and revocation, role
grants, status changes, deletion and purge, data export, consent, denied authorisation, and
membership and verification decisions (including document views).

Audit writes are deliberately **not** fire-and-forget. If an entry can't be written, the
surrounding transaction rolls back so that no sensitive action happens without a trace. (Avoid
`ATOMIC_REQUESTS`, or failure audits that run inside a rolled-back request transaction will be
lost.)

## Privacy by design (NDPR / GDPR-style capabilities)

University provides technical capabilities that help deployments meet applicable law (Nigeria's
NDPA/NDPR, Ghana's Data Protection Act, Kenya's DPA, GDPR …). **It does not make a deployment
compliant by itself.**

| Principle | Capability |
| --- | --- |
| Lawful basis and consent | Append-only `ConsentRecord` with purpose, version, source, time and IP; `/me/consents/` |
| Access and portability | `/me/export/` returns machine-readable JSON with sections from every module (`users.export_data` hook) |
| Rectification | `/me/`, email change, phone verification, membership details |
| Erasure | Soft deletion; anonymisation after the grace period; modules erase their own PII (`users.purge` hook, e.g. student-number hashes and verification documents) |
| Minimisation | No profile fields assumed; student numbers stored as hashes with masked hints; optional IP truncation (`STORE_FULL_IP_ADDRESSES=False`) |
| Visibility control | Profile visibility, contact visibility, affiliations, discoverability and searchability settings |
| Retention | Configurable policies per data class, run by `university_purge` |
| Accountability | Audit log, user activity history (`/me/activity/`) |

## Data retention

| Data | Default retention | Setting |
| --- | --- | --- |
| Audit log | 730 days | `RETENTION.AUDIT_LOG_DAYS` |
| Login attempts | 90 days | `RETENTION.LOGIN_ATTEMPT_DAYS` |
| OTP challenges | 7 days | `RETENTION.OTP_CHALLENGE_DAYS` |
| Revoked/expired sessions | 90 days | `RETENTION.REVOKED_SESSION_DAYS` |
| Idempotency records | 48 hours | `RETENTION.IDEMPOTENCY_RECORD_HOURS` |
| Webhook deliveries | 30 days | `RETENTION.WEBHOOK_EVENT_DAYS` |
| Deleted accounts (before anonymisation) | 30 days | `USERS.DELETION_GRACE_PERIOD_DAYS` |
| Verification documents (after decision) | 90 days | `INSTITUTION.VERIFICATION_DOCUMENT_RETENTION_DAYS` |

Schedule `university.core.purge` (Celery beat, as in the example project) or run
`manage.py university_purge` from cron. Use `--dry-run` and `--list` to inspect.

## Secrets management

Never commit secrets. Provide `DJANGO_SECRET_KEY`, `JWT_SIGNING_KEY`, `UNIVERSITY_HMAC_KEY`,
database, cache, broker and provider credentials through environment variables or a secret
manager (see `example_project/.env.example`). Generate keys with
`python -c "import secrets; print(secrets.token_urlsafe(64))"`.

## Security testing

The suites include tests for IDOR/BOLA, privilege escalation, mass assignment, authentication
bypass (forged, `alg=none`, spliced and expired tokens), enumeration, rate-limit lockout, CSRF,
unsafe uploads, webhook forgery and replay, audit tampering, and permission boundaries across
institutions. CI also runs Bandit, pip-audit, gitleaks and CodeQL.
