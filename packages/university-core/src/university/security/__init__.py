"""Authentication and session security.

* Pluggable access tokens (JWT by default) with opaque, rotating, hashed
  refresh tokens and reuse detection.
* Device/session tracking with self-service revocation.
* API keys for trusted integrations, limited to declared permission scopes.
* Brute-force lockout, suspicious-login detection, one-time codes, MFA and
  passwordless login, and external (OAuth2/OIDC) identity providers.
"""
