"""Default values for the ``UNIVERSITY`` Django setting (Core namespace).

Every tunable in University Core lives here — there are no magic constants
scattered through the codebase. Deployments override any subset::

    UNIVERSITY = {
        "AUTH": {"JWT": {"ACCESS_TOKEN_LIFETIME_SECONDS": 600}},
        "THROTTLE_RATES": {"login": "5/min"},
    }

Optional modules keep their defaults under their own top-level key (for
example ``UNIVERSITY["INSTITUTION"]``) and never touch these.
"""

from __future__ import annotations

from typing import Any

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

DEFAULTS: dict[str, Any] = {
    # ------------------------------------------------------------------ IDs
    "IDS": {
        # 4 = random UUIDs (default, leaks nothing).
        # 7 = time-ordered UUIDs (better B-tree locality at very large scale,
        #     but encodes the creation timestamp in the identifier).
        "UUID_VERSION": 4,
    },
    # ------------------------------------------------------------------ API
    "API": {
        "URL_PREFIX": "api",
        "DEFAULT_VERSION": "v1",
        "ALLOWED_VERSIONS": ["v1"],
        # Serve OpenAPI schema/docs when drf-spectacular is installed.
        "SCHEMA_ENABLED": True,
        "DOCS_ENABLED": True,
    },
    # ----------------------------------------------------------------- AUTH
    "AUTH": {
        # Identifiers accepted by the login endpoint, in lookup order.
        # "phone" only matches *verified* phone numbers.
        "LOGIN_IDENTIFIERS": ["email", "handle", "phone"],
        # Dotted path to the TokenIssuer used for login/refresh.
        "TOKEN_ISSUER": "university.security.tokens.JWTTokenIssuer",
        "JWT": {
            "ALGORITHM": "HS256",
            # None -> derived from SECRET_KEY. Set a dedicated key in production.
            "SIGNING_KEY": None,
            # Required for asymmetric algorithms (RS256/ES256/EdDSA).
            "VERIFYING_KEY": None,
            "ISSUER": "university",
            "AUDIENCE": None,
            "ACCESS_TOKEN_LIFETIME_SECONDS": 5 * MINUTE,
            "LEEWAY_SECONDS": 10,
        },
        "REFRESH_TOKEN_LIFETIME_SECONDS": 30 * DAY,
        # Absolute lifetime of a session; the user must sign in again after it.
        "SESSION_MAX_AGE_SECONDS": 90 * DAY,
        # A session unused for this long can no longer be refreshed.
        "SESSION_IDLE_TIMEOUT_SECONDS": 14 * DAY,
        # Oldest sessions are revoked once a user exceeds this many.
        "MAX_SESSIONS_PER_USER": 25,
        # last_seen_at is only written when older than this (limits writes).
        "SESSION_TOUCH_INTERVAL_SECONDS": 5 * MINUTE,
        # Hide whether an account exists but is unverified at login time.
        "REVEAL_UNVERIFIED_ACCOUNT_ON_LOGIN": False,
        "LOCKOUT": {
            "ENABLED": True,
            "WINDOW_SECONDS": 15 * MINUTE,
            "LOCKOUT_SECONDS": 15 * MINUTE,
            # Failures for one identifier from one IP.
            "MAX_FAILURES_PER_IDENTIFIER_AND_IP": 5,
            # Failures for one identifier from anywhere (credential stuffing).
            "MAX_FAILURES_PER_IDENTIFIER": 20,
            # Failures from one IP for any identifier (password spraying).
            "MAX_FAILURES_PER_IP": 100,
        },
        "API_KEYS": {
            "ENABLED": True,
            "PREFIX": "uk",
            "HEADER": "X-API-Key",
            "MAX_PER_USER": 10,
            "DEFAULT_LIFETIME_DAYS": 365,
            "TOUCH_INTERVAL_SECONDS": 5 * MINUTE,
        },
        "MFA": {
            "ENABLED": True,
            # Channels a user may choose for one-time-code second factors.
            "CHANNELS": ["email", "sms"],
        },
        "PASSWORDLESS": {
            # Email/SMS one-time-code login. Off by default.
            "ENABLED": False,
        },
        # External identity providers (OAuth2/OIDC). Example:
        # "google": {"CLASS": "university.security.providers.oidc.OIDCIdentityProvider",
        #            "OPTIONS": {"issuer": "...", "jwks_url": "...", "audience": "..."}}
        "IDENTITY_PROVIDERS": {},
        # Link an external identity to an existing account by verified email.
        # Disabled by default: a misconfigured provider can enable takeover.
        "LINK_EXTERNAL_IDENTITY_BY_VERIFIED_EMAIL": False,
        "ALLOW_SIGNUP_VIA_IDENTITY_PROVIDER": True,
    },
    # ------------------------------------------------------------- SECURITY
    "SECURITY": {
        # Key for keyed hashes (tokens, OTPs, identifiers). None -> SECRET_KEY.
        "HMAC_KEY": None,
        # Previous keys, still accepted for verification during rotation.
        "HMAC_KEY_FALLBACKS": [],
        # Number of trusted reverse proxies in front of the app. 0 means the
        # client address is REMOTE_ADDR and forwarding headers are ignored.
        "TRUSTED_PROXY_COUNT": 0,
        "CLIENT_IP_HEADER": "HTTP_X_FORWARDED_FOR",
        # False truncates stored IPs (/24 IPv4, /48 IPv6) for privacy.
        "STORE_FULL_IP_ADDRESSES": True,
        "SUSPICIOUS_LOGIN_DETECTOR": ("university.security.detection.HeuristicSuspiciousLoginDetector"),
        "SEND_LOGIN_ALERT_EMAILS": True,
        # Accept an inbound X-Request-ID header (only behind a trusted edge).
        "TRUST_INCOMING_REQUEST_ID": False,
        # Headers applied to API responses by APISecurityHeadersMiddleware.
        "API_CONTENT_SECURITY_POLICY": "default-src 'none'; frame-ancestors 'none'",
        "API_CACHE_CONTROL": "no-store",
    },
    # ------------------------------------------------------------------ OTP
    "OTP": {
        "LENGTH": 6,
        "TTL_SECONDS": 10 * MINUTE,
        "MAX_ATTEMPTS": 5,
        "RESEND_COOLDOWN_SECONDS": 60,
        "MAX_ISSUES_PER_DESTINATION_PER_HOUR": 5,
    },
    # ---------------------------------------------------------------- USERS
    "USERS": {
        "ALLOW_REGISTRATION": True,
        # "verify_first": registration always answers 202 and the account is
        #   activated by the emailed link (no account enumeration).
        # "open": registration answers 201 and returns tokens immediately.
        "REGISTRATION_MODE": "verify_first",
        "HANDLE_MIN_LENGTH": 3,
        "HANDLE_MAX_LENGTH": 30,
        "RESERVED_HANDLES": [
            "admin",
            "administrator",
            "api",
            "anonymous",
            "help",
            "me",
            "mod",
            "moderator",
            "null",
            "root",
            "security",
            "settings",
            "staff",
            "support",
            "system",
            "university",
            "undefined",
        ],
        "EMAIL_VERIFICATION_TTL_SECONDS": 3 * DAY,
        "EMAIL_CHANGE_TTL_SECONDS": 1 * DAY,
        # Soft-deleted accounts are anonymised after this grace period.
        "DELETION_GRACE_PERIOD_DAYS": 30,
        "DEFAULT_PROFILE_VISIBILITY": "public",
        # Links embedded in emails. {token}/{uid} are substituted.
        "FRONTEND_URLS": {
            "VERIFY_EMAIL": "http://localhost:3000/verify-email?token={token}",
            "CONFIRM_EMAIL_CHANGE": "http://localhost:3000/confirm-email?token={token}",
            "RESET_PASSWORD": "http://localhost:3000/reset-password?uid={uid}&token={token}",
        },
        # Override serializers without forking (dotted paths or None).
        "ME_SERIALIZER": None,
        "PUBLIC_PROFILE_SERIALIZER": None,
        # Consent purposes a user may grant or withdraw.
        "CONSENT_PURPOSES": ["terms_of_service", "privacy_policy", "marketing"],
    },
    # ------------------------------------------------------------ PROVIDERS
    "PROVIDERS": {
        "EMAIL": "university.core.providers.email.DjangoEmailProvider",
        "SMS": "university.core.providers.sms.ConsoleSMSProvider",
        "SEARCH": "university.core.providers.search.NullSearchBackend",
        "SPAM": "university.core.providers.spam.RuleBasedSpamFilter",
        "SMS_OPTIONS": {},
        "SEARCH_OPTIONS": {},
        "SPAM_OPTIONS": {},
    },
    # ---------------------------------------------------------------- TASKS
    "TASKS": {
        # ImmediateTaskBackend | CeleryTaskBackend | DjangoTaskBackend
        "BACKEND": "university.core.tasks.ImmediateTaskBackend",
        # Immediate backend only: re-raise task exceptions (useful in tests).
        "EAGER_PROPAGATE_EXCEPTIONS": False,
        # Celery queue routing: {"task.name": "queue"}.
        "QUEUES": {},
    },
    # --------------------------------------------------------------- EVENTS
    "EVENTS": {
        # Dispatch events only after the surrounding transaction commits.
        "DISPATCH_ON_COMMIT": True,
        # Re-raise synchronous handler errors (useful in tests).
        "RAISE_HANDLER_ERRORS": False,
    },
    # ----------------------------------------------------------- PAGINATION
    "PAGINATION": {
        "PAGE_SIZE": 20,
        "MAX_PAGE_SIZE": 100,
    },
    # ------------------------------------------------------- RATE LIMITING
    # "<count>/<period>" where period is s, sec, m, min, h, hour, d, day,
    # optionally with a multiplier ("10/5min"). None disables a scope.
    "THROTTLE_RATES": {
        "anon_global": "120/min",
        "user_global": "600/min",
        "login": "10/min",
        "token_refresh": "30/min",
        "registration": "5/hour",
        "password_reset": "5/hour",
        "password_change": "10/hour",
        "email_verification": "10/hour",
        "otp_request": "5/hour",
        "otp_verify": "20/hour",
        "account_delete": "5/hour",
        "data_export": "3/day",
        "api_key_create": "10/day",
        "profile_lookup": "120/min",
        "upload": "60/hour",
        "report": "30/hour",
        "webhook": "600/min",
    },
    # ---------------------------------------------------------------- AUDIT
    "AUDIT": {
        "ENABLED": True,
        # Chain each entry to its predecessor (serialises audit writes; the
        # per-entry HMAC is always on). Prefer an external WORM sink at scale.
        "HASH_CHAIN": False,
        "METADATA_MAX_BYTES": 8192,
        "SINKS": ["university.audit.sinks.DatabaseSink"],
    },
    # ------------------------------------------------------------ RETENTION
    "RETENTION": {
        "AUDIT_LOG_DAYS": 730,
        "LOGIN_ATTEMPT_DAYS": 90,
        "OTP_CHALLENGE_DAYS": 7,
        "REVOKED_SESSION_DAYS": 90,
        "IDEMPOTENCY_RECORD_HOURS": 48,
        "WEBHOOK_EVENT_DAYS": 30,
    },
    # -------------------------------------------------------------- UPLOADS
    "UPLOADS": {
        "MAX_BYTES": 10 * 1024 * 1024,
        "ALLOWED_MIME_TYPES": [
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "application/pdf",
        ],
        "MAX_IMAGE_PIXELS": 40_000_000,
    },
    # ---------------------------------------------------------- IDEMPOTENCY
    "IDEMPOTENCY": {
        "HEADER": "Idempotency-Key",
        "LOCK_SECONDS": 30,
    },
    # ------------------------------------------------------------- WEBHOOKS
    "WEBHOOKS": {
        "TIMESTAMP_TOLERANCE_SECONDS": 5 * MINUTE,
    },
    # ---------------------------------------------------------------- CACHE
    "CACHE": {
        "ALIAS": "default",
        "KEY_PREFIX": "university",
        "PERMISSIONS_TTL_SECONDS": 5 * MINUTE,
    },
    # -------------------------------------------------------------- PLUGINS
    "PLUGINS": {
        "LOAD_ENTRY_POINTS": True,
        "ENTRY_POINT_GROUP": "university.plugins",
        # Entry-point plugin names to skip.
        "DISABLED": [],
    },
    # --------------------------------------------------------------- HEALTH
    "HEALTH": {
        # Readiness checks to run (built-in and module-registered).
        "READINESS_CHECKS": ["database", "cache"],
    },
    # ---------------------------------------------------------- PERMISSIONS
    "PERMISSIONS": {
        # Superusers implicitly hold every permission.
        "SUPERUSER_BYPASS": True,
    },
}
