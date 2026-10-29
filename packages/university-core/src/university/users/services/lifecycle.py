"""Account lifecycle: suspension, bans, deletion, restoration and purging."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.conf import university_settings
from university.core.events import publish
from university.core.exceptions import Conflict, PermissionDenied, ValidationError
from university.core.hooks import Hook, hooks
from university.permissions.services import authorize
from university.users import events
from university.users.constants import UserStatus


def _protect_privileged(actor: Any, user: Any) -> None:
    if actor is not None and user.pk == actor.pk:
        raise PermissionDenied("You cannot change your own account status.", code="self_action")
    if user.is_superuser and not getattr(actor, "is_superuser", False):
        raise PermissionDenied()


def _set_status(user: Any, status: str, *, reason: str = "", until: dt.datetime | None = None) -> None:
    user.status = status
    user.status_reason = reason[:255]
    user.status_changed_at = timezone.now()
    user.suspended_until = until
    user.rotate_security_stamp()
    user.save(update_fields=["status", "status_reason", "status_changed_at", "suspended_until", "security_stamp"])


def _revoke_credentials(user: Any, *, actor: Any, reason: str) -> None:
    from university.security.services.api_keys import revoke_all_api_keys
    from university.security.services.sessions import revoke_user_sessions

    revoke_user_sessions(user, actor=actor, reason=reason)
    revoke_all_api_keys(user, actor=actor)


@transaction.atomic
def suspend_user(*, actor: Any, user: Any, reason: str, until: dt.datetime | None = None) -> Any:
    authorize(actor, "users.suspend", audit_denial=True)
    _protect_privileged(actor, user)
    if until is not None and until <= timezone.now():
        raise ValidationError(details={"until": ["Must be in the future."]})
    _set_status(user, UserStatus.SUSPENDED, reason=reason, until=until)
    _revoke_credentials(user, actor=actor, reason="suspended")
    audit(
        AuditAction.ACCOUNT_SUSPENDED,
        actor=actor,
        target=user,
        metadata={"reason": reason, "until": until.isoformat() if until else None},
    )
    publish(events.USER_SUSPENDED, {"user_id": user.pk, "until": until}, actor=actor)
    return user


@transaction.atomic
def ban_user(*, actor: Any, user: Any, reason: str) -> Any:
    authorize(actor, "users.ban", audit_denial=True)
    _protect_privileged(actor, user)
    _set_status(user, UserStatus.BANNED, reason=reason)
    _revoke_credentials(user, actor=actor, reason="banned")
    audit(AuditAction.ACCOUNT_BANNED, actor=actor, target=user, metadata={"reason": reason})
    publish(events.USER_BANNED, {"user_id": user.pk}, actor=actor)
    return user


@transaction.atomic
def reactivate_user(*, actor: Any, user: Any, reason: str = "") -> Any:
    authorize(actor, "users.suspend", audit_denial=True)
    _protect_privileged(actor, user)
    if user.status not in (UserStatus.SUSPENDED, UserStatus.BANNED, UserStatus.INACTIVE):
        raise Conflict("The account is not suspended, banned or inactive.", code="invalid_status")
    _set_status(user, UserStatus.ACTIVE, reason=reason)
    audit(AuditAction.ACCOUNT_REACTIVATED, actor=actor, target=user, metadata={"reason": reason})
    publish(events.USER_REACTIVATED, {"user_id": user.pk}, actor=actor)
    return user


def _mark_deleted(user: Any, *, actor: Any, reason: str) -> Any:
    user.status = UserStatus.DELETED
    user.status_reason = reason[:255]
    user.status_changed_at = timezone.now()
    user.deleted_at = timezone.now()
    user.rotate_security_stamp()
    user.save(update_fields=["status", "status_reason", "status_changed_at", "deleted_at", "security_stamp"])
    _revoke_credentials(user, actor=actor, reason="deleted")
    audit(AuditAction.ACCOUNT_DELETED, actor=actor, target=user, metadata={"reason": reason})
    publish(events.USER_DELETED, {"user_id": user.pk}, actor=actor)
    return user


@transaction.atomic
def delete_account(user: Any, *, password: str) -> Any:
    """Self-service account deletion (soft; anonymised after the grace period)."""
    if user.has_usable_password() and not user.check_password(password or ""):
        raise ValidationError(details={"password": ["Incorrect password."]}, code="invalid_password")
    return _mark_deleted(user, actor=user, reason="self")


@transaction.atomic
def delete_user(*, actor: Any, user: Any, reason: str) -> Any:
    authorize(actor, "users.delete", audit_denial=True)
    _protect_privileged(actor, user)
    if user.status == UserStatus.DELETED:
        raise Conflict("The account is already deleted.", code="already_deleted")
    return _mark_deleted(user, actor=actor, reason=reason)


@transaction.atomic
def restore_user(*, actor: Any, user: Any) -> Any:
    authorize(actor, "users.restore", audit_denial=True)
    if user.status != UserStatus.DELETED or user.anonymized_at is not None:
        raise Conflict("Only deleted accounts within the grace period can be restored.", code="not_restorable")
    user.status = UserStatus.ACTIVE
    user.deleted_at = None
    user.status_reason = ""
    user.status_changed_at = timezone.now()
    user.save(update_fields=["status", "deleted_at", "status_reason", "status_changed_at"])
    audit(AuditAction.ACCOUNT_RESTORED, actor=actor, target=user)
    publish(events.USER_RESTORED, {"user_id": user.pk}, actor=actor)
    return user


@transaction.atomic
def purge_user(user: Any) -> Any:
    """Irreversibly anonymise a deleted account's personal data.

    The row is kept (anonymised) so foreign keys, audit trails and
    moderation history stay intact without identifying the person.
    """
    if user.status != UserStatus.DELETED or user.anonymized_at is not None:
        return user
    user_id = user.pk
    hooks.call(Hook.USER_PURGE, user_id)
    user.email = f"deleted+{user.pk.hex}@deleted.invalid"
    user.pending_email = ""
    user.handle = None
    user.display_name = ""
    if user.avatar:
        user.avatar.delete(save=False)
    user.phone_number = None
    user.phone_verified_at = None
    user.email_verified_at = None
    user.locale = ""
    user.timezone = ""
    user.set_unusable_password()
    user.anonymized_at = timezone.now()
    user.save()
    for related in ("privacy_settings", "notification_settings", "security_settings"):
        obj = getattr(user, related, None)
        if obj is not None:
            obj.delete()
    user.consents.all().delete()
    audit(AuditAction.ACCOUNT_PURGED, actor=None, target_type="university_users.user", target_id=user_id)
    publish(events.USER_PURGED, {"user_id": user_id})
    return user


def purge_expired_deleted_users(cutoff: dt.datetime, dry_run: bool) -> int:
    qs = get_user_model().all_objects.filter(
        status=UserStatus.DELETED, deleted_at__lt=cutoff, anonymized_at__isnull=True
    )
    if dry_run:
        return qs.count()
    count = 0
    for user in qs.iterator(chunk_size=200):
        purge_user(user)
        count += 1
    return count


def deletion_cutoff() -> dt.datetime | None:
    days = university_settings.get("USERS.DELETION_GRACE_PERIOD_DAYS", 30)
    return None if days is None else timezone.now() - dt.timedelta(days=int(days))
