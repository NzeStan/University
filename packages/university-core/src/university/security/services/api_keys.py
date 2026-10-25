"""API keys for trusted integrations.

Format: ``<prefix>_<lookup>_<secret>`` — e.g. ``uk_7HQ2M4XA_Yb3…``. The
``lookup`` part is an indexed public identifier; the full key is verified
against its keyed hash in constant time. Keys are shown once.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import secrets
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.conf import university_settings
from university.core.crypto import generate_token, keyed_hash, verify_keyed_hash
from university.core.events import publish
from university.core.exceptions import NotFound, PermissionDenied, ValidationError
from university.core.registry import registry
from university.security import events
from university.security.models import APIKey
from university.users.constants import UserStatus

KEY_PURPOSE = "api-key"
_LOOKUP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True)
class CreatedAPIKey:
    api_key: APIKey
    raw_key: str


def _cfg() -> dict[str, Any]:
    return university_settings.get("AUTH.API_KEYS")


def _validate_scopes(scopes: list[str]) -> list[str]:
    if not isinstance(scopes, list) or not scopes:
        raise ValidationError(details={"scopes": ["List at least one permission scope."]})
    unknown = [s for s in scopes if s != "*" and not registry.permission_exists(s)]
    if unknown:
        raise ValidationError(details={"scopes": [f"Unknown permissions: {', '.join(unknown)}"]})
    return sorted(set(scopes))


def _validate_ips(cidrs: list[str]) -> list[str]:
    clean = []
    for cidr in cidrs or []:
        try:
            clean.append(str(ipaddress.ip_network(cidr, strict=False)))
        except ValueError:
            raise ValidationError(details={"allowed_ips": [f"Invalid network: {cidr}"]}) from None
    return clean


@transaction.atomic
def create_api_key(
    user: Any,
    *,
    name: str,
    scopes: list[str],
    allowed_ips: list[str] | None = None,
    expires_at: dt.datetime | None = None,
) -> CreatedAPIKey:
    cfg = _cfg()
    if not cfg.get("ENABLED", True):
        raise PermissionDenied("API keys are disabled.", code="api_keys_disabled")
    active = APIKey.objects.filter(user=user, revoked_at__isnull=True).count()
    if active >= int(cfg.get("MAX_PER_USER", 10)):
        raise ValidationError("You have reached the maximum number of API keys.", code="api_key_limit")
    if expires_at is None and cfg.get("DEFAULT_LIFETIME_DAYS"):
        expires_at = timezone.now() + dt.timedelta(days=int(cfg["DEFAULT_LIFETIME_DAYS"]))
    if expires_at is not None and expires_at <= timezone.now():
        raise ValidationError(details={"expires_at": ["Must be in the future."]})
    lookup = "".join(secrets.choice(_LOOKUP_ALPHABET) for _ in range(12))
    raw = f"{cfg.get('PREFIX', 'uk')}_{lookup}_{generate_token(32)}"
    api_key = APIKey.objects.create(
        user=user,
        name=name.strip()[:100] or "API key",
        lookup=lookup,
        key_hash=keyed_hash(raw, purpose=KEY_PURPOSE),
        scopes=_validate_scopes(scopes),
        allowed_ips=_validate_ips(allowed_ips or []),
        expires_at=expires_at,
    )
    audit(AuditAction.API_KEY_CREATED, actor=user, target=api_key, metadata={"scopes": api_key.scopes})
    publish(events.API_KEY_CREATED, {"user_id": user.pk, "api_key_id": api_key.pk}, actor=user)
    return CreatedAPIKey(api_key=api_key, raw_key=raw)


def _ip_allowed(api_key: APIKey, ip: str | None) -> bool:
    if not api_key.allowed_ips:
        return True
    if not ip:
        return False
    addr = ipaddress.ip_address(ip)
    return any(addr in ipaddress.ip_network(cidr) for cidr in api_key.allowed_ips)


def authenticate_api_key(raw: str, *, ip_address: str | None) -> APIKey | None:
    parts = raw.split("_", 2)
    if len(parts) != 3 or len(raw) > 200:
        return None
    api_key = APIKey.objects.select_related("user").filter(lookup=parts[1]).first()
    if api_key is None:
        # Spend comparable time to avoid a lookup-existence oracle.
        verify_keyed_hash(raw, "0" * 64, purpose=KEY_PURPOSE)
        return None
    if not verify_keyed_hash(raw, api_key.key_hash, purpose=KEY_PURPOSE):
        return None
    if not api_key.is_active or api_key.user.status != UserStatus.ACTIVE or not _ip_allowed(api_key, ip_address):
        return None
    now = timezone.now()
    interval = int(_cfg().get("TOUCH_INTERVAL_SECONDS", 300))
    if api_key.last_used_at is None or api_key.last_used_at < now - dt.timedelta(seconds=interval):
        APIKey.objects.filter(pk=api_key.pk).update(last_used_at=now)
    return api_key


def revoke_api_key(user: Any, api_key_id: Any) -> None:
    api_key = APIKey.objects.filter(pk=api_key_id, user=user).first()
    if api_key is None:
        raise NotFound("API key not found.")
    if APIKey.objects.filter(pk=api_key.pk, revoked_at__isnull=True).update(revoked_at=timezone.now()):
        audit(AuditAction.API_KEY_REVOKED, actor=user, target=api_key)
        publish(events.API_KEY_REVOKED, {"user_id": user.pk, "api_key_id": api_key.pk}, actor=user)


def revoke_all_api_keys(user: Any, *, actor: Any) -> int:
    count = APIKey.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
    if count:
        audit(AuditAction.API_KEY_REVOKED, actor=actor, target=user, metadata={"count": count})
    return count
