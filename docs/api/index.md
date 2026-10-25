# API

The live, authoritative contract is the OpenAPI schema at `/api/schema/` (Swagger UI at
`/api/docs/`), generated from the code and validated in CI with `--fail-on-warn`.

## Conventions

- **Versioning**: `/api/v1/…`. Each version is a URL namespace (`request.version == "v1"`), and a
  `v2` can run alongside `v1`. Breaking changes are never made inside a published version.
- **Identifiers**: UUIDs in every URL and body. Integer ids never appear.
- **Authentication**: `Authorization: Bearer <access>`, `Authorization: Api-Key <key>`, or session
  cookie + CSRF token (internal tools).
- **Content**: JSON (`application/json`); multipart only for uploads.
- **Times**: ISO 8601 with timezone (UTC).
- **Idempotency**: endpoints that create irreversible effects accept `Idempotency-Key`. A replay
  returns the stored response with `Idempotent-Replayed: true`. A key reused with a different
  payload returns `422`; a key still in progress returns `409`.
- **Correlation**: every response carries `X-Request-ID`, which also appears in error bodies and
  logs.

## Errors

Every error has the same shape:

```json
{
  "error": {
    "code": "permission_denied",
    "message": "You do not have permission to perform this action.",
    "details": {},
    "request_id": "6f1c0d6b6a9b4f0c9d0e3a7f2b1c4d5e"
  }
}
```

| Status | Typical `code` values |
| --- | --- |
| 400 | `invalid` (field errors in `details`), `invalid_token`, `invalid_code`, `parse_error` |
| 401 | `not_authenticated`, `authentication_failed`, `invalid_credentials`, `token_invalid`, `token_expired`, `refresh_invalid` |
| 403 | `permission_denied`, `account_suspended`, `account_banned`, `privilege_escalation`, `registration_closed` |
| 404 | `not_found` (also returned for objects you may not see) |
| 409 | `conflict`, `membership_exists`, `role_already_assigned`, `idempotency_in_progress` |
| 422 | `idempotency_key_reused` |
| 429 | `rate_limited`, `login_locked` (`details.retry_after` plus a `Retry-After` header) |
| 500 | `server_error`: no internals are ever included |

## Pagination

- Admin and data lists: `?page=2&page_size=50` → `{"count", "next", "previous", "results"}`.
- Feeds and timelines: cursor pagination, `?cursor=…` → `{"next", "previous", "results"}`.
- `page_size` is capped by `PAGINATION.MAX_PAGE_SIZE`.

## Filtering

Only documented query parameters are honoured, such as `?country=NG&type=university&q=tech`.
Unknown parameters are ignored and are never turned into ORM lookups.

## Deprecation policy

A deprecated endpoint or field keeps working until the announced removal version. It's listed in
`CHANGELOG.md` under **Deprecated** with its replacement and removal version, marked
`deprecated: true` in the schema, and answered with a `Deprecation` header where practical.

---

## Endpoint catalogue (Core)

### Accounts

| Method & path | Auth | Description |
| --- | --- | --- |
| `POST /auth/register/` | — | Register. `202` (verify_first) or `201` with tokens (open) |
| `POST /auth/email/verify/` | — | Confirm the emailed verification token |
| `POST /auth/email/verify/resend/` | — | Resend verification (generic `202`) |
| `POST /auth/password/reset/` | — | Request reset (generic `202`) |
| `POST /auth/password/reset/confirm/` | — | `uid`, `token`, `new_password` |
| `POST /auth/email/change/confirm/` | — | Confirm a new email address |
| `GET/PATCH/DELETE /me/` | user | Own account; profile fields only; delete requires password |
| `POST /me/password/` | user | Change password; returns a fresh access token for this session |
| `POST /me/email/` | user | Start an email change (generic `202`) |
| `POST/DELETE /me/phone/` · `POST /me/phone/verify/` | user | Phone verification by OTP |
| `GET/PATCH /me/privacy/` · `/me/notifications/` · `/me/security/` | user | Preferences |
| `GET/POST /me/consents/` | user | Consent history / record a decision |
| `GET /me/export/` | user | Data portability export (JSON) |
| `GET /me/activity/` | user | Own security activity (cursor paginated) |
| `GET /users/{id}/` · `GET /users/by-handle/{handle}/` | optional | Public profile (privacy-aware; 404 when hidden) |
| `POST /users/{id}/suspend\|ban\|reactivate\|restore/` | `users.*` | Staff account actions (audited) |

### Authentication

| Method & path | Auth | Description |
| --- | --- | --- |
| `POST /auth/login/` | — | `200` tokens or `202` MFA challenge |
| `POST /auth/login/mfa/` | — | Complete MFA |
| `POST /auth/token/refresh/` | — | Rotate the refresh token |
| `POST /auth/logout/` | user | Revoke the current session |
| `POST /auth/passwordless/` · `POST /auth/passwordless/verify/` | — | Passwordless code login (if enabled) |
| `POST /auth/providers/{provider}/login/` | — | OIDC/OAuth sign-in |
| `GET /me/sessions/` · `DELETE /me/sessions/{id}/` · `POST /me/sessions/revoke-others/` | user | Devices |
| `GET/POST /me/api-keys/` · `DELETE /me/api-keys/{id}/` | user | API keys (secret shown once) |
| `GET /me/identities/` · `POST /me/identities/{provider}/link/` · `DELETE /me/identities/{id}/` | user | Linked providers |
| `POST /me/mfa/enrol/` · `/me/mfa/confirm/` · `/me/mfa/disable/` | user | MFA management |

### Permissions and audit

| Method & path | Auth | Description |
| --- | --- | --- |
| `GET /permissions/` | `permissions.roles.view` | Declared permissions |
| `GET/POST /roles/` · `GET/PATCH /roles/{id}/` | view / `permissions.roles.manage` | Custom roles (system roles are read-only) |
| `GET/POST /role-assignments/?scope_type=&scope_id=&user=` | scoped view / assign | Grant roles at a scope (no escalation) |
| `DELETE /role-assignments/{id}/` | scoped assign | Revoke |
| `GET /me/permissions/?scope_type=&scope_id=` | user | Effective permissions (for UIs) |
| `GET /audit/logs/?action=&category=&outcome=&actor=&target_type=&target_id=&since=&until=` | `audit.view` | Audit log |

### Platform

| Method & path | Description |
| --- | --- |
| `GET /meta/modules/` | Installed modules (versions only for staff) |
| `GET /health/` · `/health/live/` · `/health/ready/` | Liveness and readiness (`503` when a dependency fails) |

Module endpoints: [institution](../modules/institution.md#api) · [social](../modules/social.md#api-apiv1social) · [moderation](../modules/moderation.md#api-apiv1moderation) · [anonymous](../modules/anonymous.md#api-apiv1anonymous) · [community](../modules/community.md#api-apiv1).
