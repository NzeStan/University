"""Audit action names used by University Core.

Modules define their own constants following the same ``<area>.<subject>.<verb>``
convention (e.g. ``anonymous.identity.revealed``). The first segment is the
default audit *category*.
"""

from __future__ import annotations


class AuditCategory:
    AUTH = "auth"
    SECURITY = "security"
    ACCOUNT = "account"
    PRIVACY = "privacy"
    PERMISSION = "permission"
    MODERATION = "moderation"
    ADMIN = "admin"
    SYSTEM = "system"


class AuditOutcome:
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


class AuditAction:
    # Authentication
    LOGIN_SUCCEEDED = "auth.login.succeeded"
    LOGIN_FAILED = "auth.login.failed"
    LOGIN_LOCKED = "auth.login.locked"
    LOGIN_MFA_CHALLENGED = "auth.login.mfa_challenged"
    LOGOUT = "auth.logout"
    TOKEN_REFRESHED = "auth.token.refreshed"
    SESSION_REVOKED = "auth.session.revoked"
    SESSIONS_REVOKED = "auth.sessions.revoked"
    EXTERNAL_IDENTITY_LINKED = "auth.external_identity.linked"
    EXTERNAL_IDENTITY_UNLINKED = "auth.external_identity.unlinked"

    # Security
    REFRESH_TOKEN_REUSED = "security.refresh_token.reused"
    SUSPICIOUS_LOGIN = "security.login.suspicious"
    API_KEY_CREATED = "security.api_key.created"
    API_KEY_REVOKED = "security.api_key.revoked"
    MFA_ENABLED = "security.mfa.enabled"
    MFA_DISABLED = "security.mfa.disabled"
    OTP_LOCKED = "security.otp.locked"

    # Account
    ACCOUNT_REGISTERED = "account.registered"
    ACCOUNT_REGISTRATION_DUPLICATE = "account.registration.duplicate"
    EMAIL_VERIFIED = "account.email.verified"
    EMAIL_CHANGE_REQUESTED = "account.email.change_requested"
    EMAIL_CHANGED = "account.email.changed"
    PHONE_VERIFIED = "account.phone.verified"
    PHONE_REMOVED = "account.phone.removed"
    PASSWORD_CHANGED = "account.password.changed"
    PASSWORD_RESET_REQUESTED = "account.password.reset_requested"
    PASSWORD_RESET_COMPLETED = "account.password.reset_completed"
    ACCOUNT_SUSPENDED = "account.suspended"
    ACCOUNT_BANNED = "account.banned"
    ACCOUNT_REACTIVATED = "account.reactivated"
    ACCOUNT_DELETED = "account.deleted"
    ACCOUNT_RESTORED = "account.restored"
    ACCOUNT_PURGED = "account.purged"
    PROFILE_PHOTO_CHANGED = "account.photo.changed"
    PROFILE_PHOTO_REMOVED = "account.photo.removed"

    # Privacy
    DATA_EXPORTED = "privacy.data.exported"
    CONSENT_RECORDED = "privacy.consent.recorded"

    # Permissions
    ROLE_ASSIGNED = "permission.role.assigned"
    ROLE_REVOKED = "permission.role.revoked"
    ROLE_CREATED = "permission.role.created"
    ROLE_UPDATED = "permission.role.updated"
    PERMISSION_DENIED = "permission.denied"

    # Audit
    AUDIT_LOG_VIEWED = "security.audit_log.viewed"
