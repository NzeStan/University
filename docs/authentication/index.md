# Authentication

Authentication is **pluggable**. The recommended DRF configuration enables three classes; you
can remove or replace any of them and nothing else assumes JWT:

```python
"DEFAULT_AUTHENTICATION_CLASSES": [
    "university.security.authentication.JWTAuthentication",      # Bearer access tokens
    "university.security.authentication.APIKeyAuthentication",   # trusted integrations
    "rest_framework.authentication.SessionAuthentication",       # admin/internal; CSRF enforced
]
```

## Sessions and tokens

Each sign-in creates a **session** (`UserSession`), which represents a device. Two tokens are
bound to it:

| Token | Format | Lifetime | Storage |
| --- | --- | --- | --- |
| Access | JWT (pluggable via `AUTH.TOKEN_ISSUER`) | 5 minutes | Not stored; validated on each request |
| Refresh | Opaque random string (`rt_…`) | 30 days, sliding; capped by the 90-day session maximum and the 14-day idle timeout | HMAC only; never stored in plaintext |

Each request with an access token checks that:

1. the signature verifies with the **pinned** algorithm (`alg=none` and algorithm confusion are
   rejected) and `exp`, `iat`, `iss`, `aud` (if set), `sub`, `sid` and `jti` are valid;
2. the session exists, isn't revoked or expired, and belongs to `sub`;
3. the user is `active`;
4. the token's security-stamp fingerprint and the session's stamp match the user's current
   **security stamp**.

The stamp rotates on password change or reset, suspension, ban and deletion. That instantly
invalidates every token issued before, with no token blacklist to maintain.

### Refresh rotation and reuse detection

`POST /api/v1/auth/token/refresh/ {"refresh": "rt_…"}` returns a new pair and marks the old
refresh token as used, using an atomic compare-and-set. Presenting a used token again means it was
copied, so **the whole session is revoked**. A `security.refresh_token.reused` audit entry and
event are recorded.

### Flows

```http
POST /api/v1/auth/login/            {"identifier": "ada@uni.edu.ng", "password": "…", "device_name": "Pixel 8"}
→ 200 {"token_type": "Bearer", "access": "…", "refresh": "rt_…", "access_expires_at": "…", "session_id": "…"}
→ 202 {"mfa_required": true, "challenge_id": "…", "channel": "email", "destination": "a***a@uni.edu.ng"}

POST /api/v1/auth/login/mfa/        {"challenge_id": "…", "code": "123456"}
POST /api/v1/auth/token/refresh/    {"refresh": "rt_…"}
POST /api/v1/auth/logout/           (revokes the current session)
GET  /api/v1/me/sessions/           DELETE /api/v1/me/sessions/{id}/    POST /api/v1/me/sessions/revoke-others/
```

`identifier` can be an email address, a handle or a **verified** phone number (configurable).

## Brute-force protection

Failed logins increment three counters in the shared cache: identifier+IP (5), identifier (20) and
IP (100), within a 15-minute window. Reaching a threshold locks that key for 15 minutes and returns
`429 login_locked` with `Retry-After`, without even checking the password. Attempts are recorded
in `LoginAttempt` with the identifier stored only as a hash. Unknown accounts still run the password
hasher, so response timing doesn't reveal whether an account exists.

Behind proxies, set `SECURITY.TRUSTED_PROXY_COUNT` so the real client IP is used. Never trust
`X-Forwarded-For` without it.

## Suspicious login detection

`SECURITY.SUSPICIOUS_LOGIN_DETECTOR` (default: heuristic) flags sign-ins where the device id,
network (/24 or /48) **and** user agent all differ from the user's recent sessions. The user gets
a login-alert email (unless they opted out) and a `security.login.suspicious` event is published
for other modules, such as notifications. Implement `SuspiciousLoginDetector.assess(user, meta)`
to plug in geo-IP or a risk engine.

## API keys

For trusted server-to-server integrations:

```http
POST /api/v1/me/api-keys/  {"name": "Timetable sync", "scopes": ["institution.structure.manage"],
                            "allowed_ips": ["10.0.0.0/8"], "expires_at": "2027-01-01T00:00:00Z"}
→ 201 {..., "key": "uk_7HQ2M4XA9KLP_…"}      # shown once
```

Send the key as `Authorization: Api-Key <key>` or `X-API-Key: <key>`. A key can **never exceed its
scopes**, even when its owner is a superuser, and it can't create other keys. Keys are stored as
HMACs, looked up by their public `lookup` part and compared in constant time. They can expire,
be restricted to IP ranges and be revoked.

## One-time codes and MFA

OTP challenges (email or SMS) are random and short-lived, with 5 atomic attempts each. Codes are
stored as HMACs bound to the challenge id and can be used only once. Requesting a new code
supersedes the old one. Issuing is rate limited per destination (60-second cooldown, 5 per hour).

Enrol MFA: `POST /me/mfa/enrol/ {"channel": "email"|"sms"}` sends a code, then
`POST /me/mfa/confirm/` enables MFA and signs out other sessions. Disable it with
`POST /me/mfa/disable/ {"password"}`.

## Passwordless

When `AUTH.PASSWORDLESS.ENABLED` is set, `POST /auth/passwordless/ {"identifier"}` returns a
challenge id whether or not the account exists (no enumeration).
`POST /auth/passwordless/verify/` then exchanges the code for tokens.

## External identity providers (OAuth2 / OIDC)

```python
UNIVERSITY = {
    "AUTH": {
        "IDENTITY_PROVIDERS": {
            "google": {
                "CLASS": "university.security.providers.oidc.OIDCIdentityProvider",
                "OPTIONS": {
                    "issuer": "https://accounts.google.com",
                    "jwks_url": "https://www.googleapis.com/oauth2/v3/certs",
                    "audience": "<client-id>",
                    "allowed_email_domains": [],
                },
            },
        }
    }
}
```

The client completes the provider's flow, then posts
`{"id_token": "...", "nonce": "..."}` to `/api/v1/auth/providers/google/login/`. The ID token's
signature (via JWKS), issuer, audience, expiry and nonce are verified.

- A first-time sign-in creates an account (`ALLOW_SIGNUP_VIA_IDENTITY_PROVIDER`).
- An existing email is **not** linked automatically, which blocks account takeover through a
  misconfigured provider. The user signs in with their password and links the provider from
  `/me/identities/{provider}/link/`. `LINK_EXTERNAL_IDENTITY_BY_VERIFIED_EMAIL` relaxes this
  rule for providers you fully trust.
- Implement `IdentityProvider.authenticate(credential) -> ExternalProfile` for other providers.

## Registration and verification

See [API → accounts](../api/index.md#accounts). In the default `verify_first` mode, registration
always answers `202` with the same body. New accounts can't sign in until the emailed link is
followed. Someone registering an address that's already in use gets nothing, and the owner gets a
"someone tried to register" notice.

## Passwords

Django's password hashing framework is used (Argon2 recommended through the `argon2` extra) along
with `AUTH_PASSWORD_VALIDATORS`. Password change and reset rotate the security stamp and revoke
other sessions. Reset tokens are Django's (single use, invalidated by any password or login
change). Passwords, tokens, reset links and authorization headers are redacted from logs.
