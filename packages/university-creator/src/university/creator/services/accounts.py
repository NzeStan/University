"""Linked external accounts: ownership, follower counts and growth snapshots.

Ownership is proven with a public challenge code placed in the account's bio
(checked through the provider's lookup), or confirmed by a reviewer for
platforms without an API. Only verified accounts with provider- or
reviewer-confirmed counts contribute to a creator's ``verified_reach``.
A verified external account can belong to only one creator.
"""

from __future__ import annotations

import datetime as dt
import secrets
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from university.audit.services import record as audit
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.ratelimit import rate_limit
from university.core.tasks import task
from university.creator import events
from university.creator.conf import creator_settings
from university.creator.constants import CountSource, OwnershipStatus
from university.creator.models import LinkedAccount, LinkedAccountSnapshot
from university.creator.providers import ExternalProfile, get_provider, normalize_handle, safe_fetch
from university.creator.selectors import own_profile
from university.creator.services.profiles import recalculate_reach
from university.permissions.services import authorize


def _challenge() -> str:
    return "UNIV-" + secrets.token_hex(4).upper()


def _own_account(user: Any, account_id: Any) -> LinkedAccount:
    account = LinkedAccount.objects.select_related("profile").filter(pk=account_id, profile__user=user).first()
    if account is None:
        raise NotFound("Account not found.")
    return account


def _snapshot(account: LinkedAccount) -> None:
    if account.follower_count is None:
        return
    LinkedAccountSnapshot.objects.update_or_create(
        account=account, date=timezone.localdate(), defaults={"follower_count": account.follower_count}
    )


def _apply_external(account: LinkedAccount, external: ExternalProfile) -> None:
    account.external_id = external.external_id[:128]
    account.display_name = external.display_name[:150]
    if external.url:
        account.url = external.url[:300]
    if external.follower_count is not None:
        account.follower_count = external.follower_count
        account.count_source = CountSource.PROVIDER
    account.last_synced_at = timezone.now()


@transaction.atomic
def link_account(*, user: Any, provider: str, handle: str, follower_count: int | None = None) -> LinkedAccount:
    rate_limit("creator_link_account", key=str(user.pk))
    profile = own_profile(user)
    provider_obj = get_provider(provider)
    handle = normalize_handle(handle)
    if profile.linked_accounts.count() >= int(creator_settings.get("MAX_LINKED_ACCOUNTS", 15)):
        raise ValidationError("You've linked the maximum number of accounts.", code="account_limit")
    if follower_count is not None and follower_count < 0:
        raise ValidationError(details={"follower_count": ["Must be zero or more."]})
    account = LinkedAccount(
        profile=profile,
        provider=provider,
        handle=handle,
        handle_key=handle.lower(),
        url=provider_obj.profile_url(handle)[:300],
        follower_count=follower_count,
        count_source=CountSource.SELF_REPORTED,
        ownership=OwnershipStatus.UNVERIFIED if provider_obj.supports_lookup else OwnershipStatus.PENDING_REVIEW,
        challenge=_challenge(),
    )
    try:
        with transaction.atomic():
            account.save()
    except IntegrityError:
        raise Conflict("You've already linked this account.", code="account_exists") from None
    return account


def _verified_elsewhere(account: LinkedAccount) -> bool:
    return (
        LinkedAccount.objects.filter(
            provider=account.provider, handle_key=account.handle_key, ownership=OwnershipStatus.VERIFIED
        )
        .exclude(pk=account.pk)
        .exists()
    )


def _mark_verified(account: LinkedAccount) -> None:
    if _verified_elsewhere(account):
        raise Conflict("Another creator has verified this account.", code="account_claimed")
    account.ownership = OwnershipStatus.VERIFIED
    account.verified_at = timezone.now()
    try:
        with transaction.atomic():
            account.save()
    except IntegrityError:
        raise Conflict("Another creator has verified this account.", code="account_claimed") from None
    _snapshot(account)
    recalculate_reach(account.profile)
    publish(
        events.ACCOUNT_VERIFIED,
        {"account_id": account.pk, "profile_id": account.profile_id, "provider": account.provider},
    )


@transaction.atomic
def verify_account(*, user: Any, account_id: Any) -> LinkedAccount:
    """Check that the challenge code is in the account's public bio."""
    rate_limit("creator_verify_account", key=str(user.pk))
    account = _own_account(user, account_id)
    if account.ownership == OwnershipStatus.VERIFIED:
        return account
    provider = get_provider(account.provider)
    if not provider.supports_lookup:
        raise Conflict("This platform is verified by our reviewers.", code="manual_review")
    external = safe_fetch(provider, account.handle)
    if external is None:
        raise ValidationError("We couldn't find that account.", code="account_not_found")
    if account.challenge not in external.bio:
        raise ValidationError(
            f"Add {account.challenge} to your bio on {provider.label}, then try again.",
            code="challenge_not_found",
        )
    _apply_external(account, external)
    _mark_verified(account)
    return account


@transaction.atomic
def confirm_account(*, actor: Any, account_id: Any, follower_count: int | None = None) -> LinkedAccount:
    """A reviewer confirms ownership (and optionally the follower count) for manual platforms."""
    authorize(actor, "creator.verify", audit_denial=True)
    account = LinkedAccount.objects.select_for_update().select_related("profile").filter(pk=account_id).first()
    if account is None:
        raise NotFound("Account not found.")
    if account.profile.user_id == actor.pk:
        raise PermissionDenied("You can't confirm your own account.", code="self_review")
    if follower_count is not None:
        if follower_count < 0:
            raise ValidationError(details={"follower_count": ["Must be zero or more."]})
        account.follower_count = follower_count
        account.count_source = CountSource.REVIEWER
    _mark_verified(account)
    audit("creator.account.confirmed", actor=actor, target=account, category="creator")
    return account


@transaction.atomic
def update_account(
    *, user: Any, account_id: Any, follower_count: int | None = None, is_public: bool | None = None
) -> LinkedAccount:
    account = _own_account(user, account_id)
    if follower_count is not None:
        if account.count_source in (CountSource.PROVIDER, CountSource.REVIEWER):
            raise Conflict("This count is confirmed and can't be edited.", code="count_confirmed")
        account.follower_count = max(int(follower_count), 0)
    if is_public is not None:
        account.is_public = bool(is_public)
    account.save()
    return account


@transaction.atomic
def unlink_account(*, user: Any, account_id: Any) -> None:
    account = _own_account(user, account_id)
    profile = account.profile
    account.delete()
    recalculate_reach(profile)


def sync_account(account: LinkedAccount) -> bool:
    """Refresh a verified account from its provider. True if updated."""
    provider = get_provider(account.provider)
    if account.ownership != OwnershipStatus.VERIFIED or not provider.supports_lookup:
        return False
    external = safe_fetch(provider, account.handle)
    if external is None:
        return False
    with transaction.atomic():
        _apply_external(account, external)
        account.save()
        _snapshot(account)
        recalculate_reach(account.profile)
    return True


@task(name="university.creator.sync_linked_accounts")
def sync_linked_accounts(limit: int = 500) -> int:
    """Refresh accounts not synced within ``SYNC_INTERVAL_HOURS`` (run hourly)."""
    from django.db.models import Q

    hours = int(creator_settings.get("SYNC_INTERVAL_HOURS", 24))
    stale = timezone.now() - dt.timedelta(hours=hours)
    due = (
        LinkedAccount.objects.filter(ownership=OwnershipStatus.VERIFIED)
        .filter(Q(last_synced_at__isnull=True) | Q(last_synced_at__lt=stale))
        .select_related("profile")
        .order_by("last_synced_at")[:limit]
    )
    synced = 0
    for account in due:
        try:
            synced += int(sync_account(account))
        except Exception:  # One failing provider must not stop the batch.
            import logging

            logging.getLogger("university.creator").warning("Sync failed for linked account %s", account.pk)
    return synced
