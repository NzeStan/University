"""Sign-in and account linking through external identity providers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.conf import university_settings
from university.core.exceptions import AuthenticationFailed, Conflict, NotFound
from university.core.http import ClientMeta
from university.security.models import ExternalIdentity
from university.security.providers import get_identity_provider
from university.security.services.login import LoginResult
from university.security.services.sessions import create_session
from university.users.constants import UserStatus
from university.users.validators import normalize_email

_FAILED = "Unable to sign in with this provider."


def login_with_provider(provider_key: str, credential: Mapping[str, Any], *, meta: ClientMeta) -> LoginResult:
    from university.users.services.registration import create_user_from_external_identity

    profile = get_identity_provider(provider_key).authenticate(credential)
    with transaction.atomic():
        identity = (
            ExternalIdentity.objects.select_related("user")
            .filter(provider=provider_key, subject=profile.subject)
            .first()
        )
        if identity is not None:
            user = identity.user
        else:
            User = get_user_model()
            email = normalize_email(profile.email)
            existing = User.all_objects.filter(email=email).first() if email else None
            if existing is not None:
                if not (
                    profile.email_verified
                    and university_settings.get("AUTH.LINK_EXTERNAL_IDENTITY_BY_VERIFIED_EMAIL", False)
                ):
                    raise AuthenticationFailed(
                        "Sign in with your password, then link this provider from your account settings.",
                        code="external_account_conflict",
                    )
                user = existing
            else:
                if not university_settings.get("AUTH.ALLOW_SIGNUP_VIA_IDENTITY_PROVIDER", True) or not email:
                    raise AuthenticationFailed(_FAILED, code="external_auth_failed")
                user = create_user_from_external_identity(
                    email=email, email_verified=profile.email_verified, display_name=profile.display_name
                )
            identity = ExternalIdentity.objects.create(
                user=user, provider=provider_key, subject=profile.subject, email=email
            )
            audit(
                AuditAction.EXTERNAL_IDENTITY_LINKED, actor=user, target=identity, metadata={"provider": provider_key}
            )
        if user.status != UserStatus.ACTIVE:
            raise AuthenticationFailed(_FAILED, code="external_auth_failed")
        ExternalIdentity.objects.filter(pk=identity.pk).update(last_login_at=timezone.now())
    session, tokens = create_session(user, meta=meta, auth_method=f"external:{provider_key}")
    return LoginResult(tokens=tokens, session=session, user=user)


@transaction.atomic
def link_provider(user: Any, provider_key: str, credential: Mapping[str, Any]) -> ExternalIdentity:
    profile = get_identity_provider(provider_key).authenticate(credential)
    try:
        with transaction.atomic():
            identity = ExternalIdentity.objects.create(
                user=user, provider=provider_key, subject=profile.subject, email=normalize_email(profile.email)
            )
    except IntegrityError:
        raise Conflict("This provider account is already linked.", code="identity_already_linked") from None
    audit(AuditAction.EXTERNAL_IDENTITY_LINKED, actor=user, target=identity, metadata={"provider": provider_key})
    return identity


@transaction.atomic
def unlink_provider(user: Any, identity_id: Any) -> None:
    identity = ExternalIdentity.objects.filter(pk=identity_id, user=user).first()
    if identity is None:
        raise NotFound("Linked identity not found.")
    if not user.has_usable_password() and ExternalIdentity.objects.filter(user=user).count() <= 1:
        raise Conflict("Set a password before removing your only sign-in method.", code="last_login_method")
    identity.delete()
    audit(AuditAction.EXTERNAL_IDENTITY_UNLINKED, actor=user, target_type="external_identity", target_id=identity_id)
