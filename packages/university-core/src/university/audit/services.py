"""Audit logging services.

:func:`record` is the single entry point for writing audit entries. It is
deliberately *not* fire-and-forget: if an entry cannot be written, the
exception propagates so that a security-sensitive operation inside the same
transaction is rolled back rather than performed without a trace.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from django.db import models, transaction
from django.utils.module_loading import import_string

from university.audit.models import AuditChainHead, AuditLog
from university.core.conf import university_settings
from university.core.context import get_request_context
from university.core.crypto import keyed_hash, verify_keyed_hash
from university.core.http import storable_ip
from university.core.logging import redact
from university.core.serialization import to_jsonable

HASH_PURPOSE = "audit-log"


def _canonical(content: Mapping[str, Any]) -> str:
    return json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)


def compute_entry_hash(entry: AuditLog) -> str:
    return keyed_hash(_canonical(entry.hashable_content()), purpose=HASH_PURPOSE)


def _limit_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    clean = redact(to_jsonable(dict(metadata)))
    limit = int(university_settings.get("AUDIT.METADATA_MAX_BYTES", 8192))
    if len(_canonical(clean)) > limit:
        return {"truncated": True, "keys": sorted(clean)[:50]}
    return clean


def _target_parts(target: Any, target_type: str | None, target_id: Any) -> tuple[str, str]:
    if target is not None and isinstance(target, models.Model):
        return target._meta.label_lower, str(target.pk)
    return (target_type or ""), ("" if target_id is None else str(target_id))


def _sinks() -> list[Any]:
    return [import_string(path)() for path in university_settings.get("AUDIT.SINKS", [])]


def record(
    action: str,
    *,
    actor: Any = None,
    target: Any = None,
    target_type: str | None = None,
    target_id: Any = None,
    category: str | None = None,
    outcome: str = AuditLog.Outcome.SUCCESS,
    scope: tuple[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog | None:
    """Write an audit entry. Returns ``None`` when auditing is disabled.

    Request metadata (ip, user agent, request id) is taken from the current
    request context unless given explicitly. ``metadata`` is redacted and
    size-limited; never put secrets in it regardless.
    """
    if not university_settings.get("AUDIT.ENABLED", True):
        return None
    ctx = get_request_context()
    actor_obj = actor if actor is not None and getattr(actor, "is_authenticated", False) else None
    resolved_type, resolved_id = _target_parts(target, target_type, target_id)
    entry = AuditLog(
        action=action,
        category=category or action.split(".", 1)[0],
        outcome=outcome,
        actor=actor_obj,
        actor_ref=str(actor_obj.pk) if actor_obj is not None else "",
        target_type=resolved_type[:100],
        target_id=resolved_id[:64],
        scope_type=(scope[0] if scope else "")[:32],
        scope_id=(str(scope[1]) if scope and scope[1] is not None else "")[:64],
        ip_address=storable_ip(ip_address or ctx.ip_address),
        user_agent=(user_agent if user_agent is not None else ctx.user_agent)[:512],
        request_id=(ctx.request_id or "")[:128],
        metadata=_limit_metadata(metadata or {}),
    )
    if university_settings.get("AUDIT.HASH_CHAIN", False):
        with transaction.atomic():
            head, _ = AuditChainHead.objects.select_for_update().get_or_create(pk=1)
            entry.previous_hash = head.last_hash
            entry.entry_hash = compute_entry_hash(entry)
            for sink in _sinks():
                sink.write(entry)
            head.last_hash = entry.entry_hash
            head.save(update_fields=["last_hash", "updated_at"])
    else:
        entry.entry_hash = compute_entry_hash(entry)
        for sink in _sinks():
            sink.write(entry)
    return entry


@dataclass(frozen=True)
class VerificationIssue:
    entry_id: str
    problem: str


def verify_entries(
    queryset: models.QuerySet | None = None, *, check_chain: bool | None = None
) -> Iterator[VerificationIssue]:
    """Yield integrity problems: modified entries and (optionally) chain breaks."""
    if check_chain is None:
        check_chain = university_settings.get("AUDIT.HASH_CHAIN", False)
    qs = (queryset if queryset is not None else AuditLog.objects.all()).order_by("created_at", "id")
    previous: str | None = None
    for entry in qs.iterator(chunk_size=2000):
        content = _canonical(entry.hashable_content())
        if not verify_keyed_hash(content, entry.entry_hash, purpose=HASH_PURPOSE):
            yield VerificationIssue(str(entry.id), "hash_mismatch")
        if check_chain and previous is not None and entry.previous_hash and entry.previous_hash != previous:
            yield VerificationIssue(str(entry.id), "chain_break")
        previous = entry.entry_hash
