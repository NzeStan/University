"""Authorization services.

``has_permission`` answers "may this user do X here?"; ``authorize`` raises
:class:`~university.core.exceptions.PermissionDenied` instead. Services call
``authorize`` themselves — authorization is never left to the client or to
view configuration alone.

Evaluation order for ``has_permission(user, code, scope)``:

1. inactive/anonymous users hold nothing;
2. superusers hold everything (``PERMISSIONS.SUPERUSER_BYPASS``);
3. API-key requests are additionally limited to the key's scopes;
4. a matching grant at the platform scope, the requested scope, or any
   ancestor scope (via registered resolvers) allows;
5. module hooks may grant implicitly (e.g. a community owner).

Grants are cached per user and invalidated whenever assignments or roles
change, so permission changes take effect immediately.
"""

from __future__ import annotations

import contextlib
import fnmatch
import uuid
from collections.abc import Iterable
from typing import Any

from django.core.cache import caches
from django.db import IntegrityError, transaction
from django.utils import timezone

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.conf import university_settings
from university.core.declarations import PLATFORM_SCOPE
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.hooks import Hook, hooks
from university.core.registry import registry
from university.permissions.models import Role, RoleAssignment
from university.permissions.scopes import PLATFORM, Scope

__all__ = [
    "PLATFORM",
    "Scope",
    "assign_role",
    "authorize",
    "get_effective_permissions",
    "has_permission",
    "invalidate_user_permissions",
    "revoke_role",
    "scopes_with_permission",
    "sync_system_roles",
]


# ------------------------------------------------------------------ cache
def _cache() -> Any:
    return caches[university_settings.get("CACHE.ALIAS", "default")]


def _prefix() -> str:
    return f"{university_settings.get('CACHE.KEY_PREFIX', 'university')}:perm"


def _version(key: str) -> str:
    return str(_cache().get(f"{_prefix()}:v:{key}") or "0")


def invalidate_user_permissions(user_id: Any) -> None:
    _cache().set(f"{_prefix()}:v:user:{user_id}", uuid.uuid4().hex, timeout=None)


def invalidate_all_permissions() -> None:
    _cache().set(f"{_prefix()}:v:global", uuid.uuid4().hex, timeout=None)


def _load_grants(user: Any) -> list[tuple[str, str, list[str], float | None]]:
    """``[(scope_type, scope_id, patterns, expires_ts)]`` for active assignments."""
    rows = (
        RoleAssignment.objects.active()
        .filter(user_id=user.pk)
        .values_list("scope_type", "scope_id", "role__permissions", "expires_at")
    )
    return [(st, sid, list(perms or []), exp.timestamp() if exp else None) for st, sid, perms, exp in rows]


def _grants(user: Any) -> list[tuple[str, str, list[str], float | None]]:
    memo = getattr(user, "_university_grants", None)
    if memo is not None:
        return memo
    key = f"{_prefix()}:grants:{user.pk}:{_version(f'user:{user.pk}')}:{_version('global')}"
    cache = _cache()
    grants = cache.get(key)
    if grants is None:
        grants = _load_grants(user)
        cache.set(key, grants, timeout=int(university_settings.get("CACHE.PERMISSIONS_TTL_SECONDS", 300)))
    now = timezone.now().timestamp()
    grants = [g for g in grants if g[3] is None or g[3] > now]
    with contextlib.suppress(AttributeError):  # exotic user objects
        user._university_grants = grants
    return grants


def _clear_memo(user: Any) -> None:
    with contextlib.suppress(AttributeError):
        del user._university_grants


# ------------------------------------------------------------- evaluation
def _matches(code: str, patterns: Iterable[str]) -> bool:
    return any(p == code or p == "*" or fnmatch.fnmatchcase(code, p) for p in patterns)


def scope_chain(scope: Scope | None) -> list[Scope]:
    """The scope followed by its ancestors (excluding platform)."""
    if scope is None or scope.is_platform:
        return []
    chain: list[Scope] = []
    seen: set[str] = set()
    frontier = [scope]
    while frontier and len(chain) < 16:
        current = frontier.pop(0)
        if current.key() in seen or current.is_platform:
            continue
        seen.add(current.key())
        chain.append(current)
        definition = registry.scope_types.get(current.type)
        if definition is not None and definition.parent_resolver is not None:
            frontier.extend(Scope(t, i) for t, i in definition.parent_resolver(current.id))
    return chain


def _api_key_allows(api_key: Any, code: str) -> bool:
    if api_key is None:
        return True
    scopes = getattr(api_key, "scopes", None)
    return bool(scopes) and _matches(code, scopes)


def has_permission(user: Any, code: str, scope: Scope | None = None, *, api_key: Any = None) -> bool:
    if user is None or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    if not _api_key_allows(api_key, code):
        return False
    if user.is_superuser and university_settings.get("PERMISSIONS.SUPERUSER_BYPASS", True):
        return True
    grants = _grants(user)
    chain = scope_chain(scope)
    scope_keys = {(s.type, s.id) for s in chain}
    for scope_type, scope_id, patterns, _exp in grants:
        applies = scope_type == PLATFORM_SCOPE or (scope_type, scope_id) in scope_keys
        if applies and _matches(code, patterns):
            return True
    for candidate in chain:
        for granted in hooks.call(Hook.PERMISSIONS_IMPLICIT_GRANTS, user, candidate):
            if granted and _matches(code, granted):
                return True
    return False


def authorize(
    user: Any, code: str, scope: Scope | None = None, *, api_key: Any = None, audit_denial: bool = False
) -> None:
    """Raise ``PermissionDenied`` unless ``user`` holds ``code`` at ``scope``."""
    if has_permission(user, code, scope, api_key=api_key):
        return
    if audit_denial:
        audit(
            AuditAction.PERMISSION_DENIED,
            actor=user,
            outcome="denied",
            scope=(scope.type, scope.id) if scope else None,
            metadata={"permission": code},
        )
    raise PermissionDenied()


def scopes_with_permission(user: Any, code: str) -> list[Scope] | None:
    """Scopes where ``user`` was granted ``code`` directly.

    Returns ``None`` when the permission holds everywhere (platform grant or
    superuser). Used to filter queues (e.g. moderation cases) efficiently;
    single-object checks should still use :func:`has_permission`.
    """
    if user is None or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return []
    if has_permission(user, code):
        return None
    scopes = {
        Scope(scope_type, scope_id)
        for scope_type, scope_id, patterns, _exp in _grants(user)
        if scope_type != PLATFORM_SCOPE and _matches(code, patterns)
    }
    for result in hooks.call(Hook.PERMISSIONS_IMPLICIT_SCOPES, user, code):
        scopes.update(Scope(scope_type, scope_id) for scope_type, scope_id in result or ())
    return sorted(scopes, key=lambda s: (s.type, s.id))


def get_effective_permissions(user: Any, scope: Scope | None = None) -> list[str]:
    """Declared permission codes the user holds at ``scope`` (for clients)."""
    return sorted(code for code in registry.permissions if has_permission(user, code, scope))


# ------------------------------------------------------------- mutations
def _validate_scope(scope: Scope) -> None:
    if scope.type not in registry.scope_types:
        raise ValidationError(details={"scope_type": [f"Unknown scope type {scope.type!r}."]})
    if not scope.is_platform and not scope.id:
        raise ValidationError(details={"scope_id": ["Required for non-platform scopes."]})


def _ensure_no_escalation(granter: Any, role: Role, scope: Scope) -> None:
    """A granter may only hand out permissions they hold at that scope."""
    if granter is None or (granter.is_superuser and university_settings.get("PERMISSIONS.SUPERUSER_BYPASS", True)):
        return
    patterns = role.permissions or []
    declared = registry.permissions
    for pattern in patterns:
        expanded = [c for c in declared if _matches(c, [pattern])] or [pattern]
        for code in expanded:
            if not has_permission(granter, code, scope):
                raise PermissionDenied("You cannot grant permissions you do not hold.", code="privilege_escalation")


@transaction.atomic
def assign_role(
    *,
    user: Any,
    role_key: str,
    scope: Scope | None = None,
    granted_by: Any = None,
    expires_at: Any = None,
) -> RoleAssignment:
    """Assign a role. When ``granted_by`` is given it is fully authorised."""
    scope = scope or PLATFORM
    _validate_scope(scope)
    try:
        role = Role.objects.get(key=role_key)
    except Role.DoesNotExist:
        raise NotFound("Role not found.") from None
    if role.scope_type != scope.type and role.scope_type != "*":
        raise ValidationError(details={"scope_type": [f"Role {role.key!r} applies to {role.scope_type!r} scopes."]})
    if granted_by is not None:
        authorize(granted_by, "permissions.roles.assign", scope, audit_denial=True)
        _ensure_no_escalation(granted_by, role, scope)
    try:
        with transaction.atomic():
            assignment = RoleAssignment.objects.create(
                user=user,
                role=role,
                scope_type=scope.type,
                scope_id=scope.id,
                granted_by=granted_by,
                expires_at=expires_at,
            )
    except IntegrityError:
        raise Conflict("The user already has this role at this scope.", code="role_already_assigned") from None
    invalidate_user_permissions(user.pk)
    _clear_memo(user)
    audit(
        AuditAction.ROLE_ASSIGNED,
        actor=granted_by,
        target=assignment,
        scope=(scope.type, scope.id),
        metadata={"role": role.key, "user_id": str(user.pk)},
    )
    publish(
        "permission.role.assigned",
        {"user_id": user.pk, "role": role.key, "scope_type": scope.type, "scope_id": scope.id},
        actor=granted_by,
    )
    return assignment


@transaction.atomic
def revoke_role(assignment: RoleAssignment, *, revoked_by: Any = None) -> RoleAssignment:
    scope = Scope(assignment.scope_type, assignment.scope_id)
    if revoked_by is not None:
        authorize(revoked_by, "permissions.roles.assign", scope, audit_denial=True)
    updated = RoleAssignment.objects.filter(pk=assignment.pk, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoked_by=revoked_by
    )
    if not updated:
        raise Conflict("This role assignment is already revoked.", code="already_revoked")
    assignment.refresh_from_db()
    invalidate_user_permissions(assignment.user_id)
    audit(
        AuditAction.ROLE_REVOKED,
        actor=revoked_by,
        target=assignment,
        scope=(scope.type, scope.id),
        metadata={"role": assignment.role.key, "user_id": str(assignment.user_id)},
    )
    publish(
        "permission.role.revoked",
        {"user_id": assignment.user_id, "role": assignment.role.key, "scope_type": scope.type, "scope_id": scope.id},
        actor=revoked_by,
    )
    return assignment


def revoke_scope_assignments(scope: Scope) -> int:
    """Revoke every assignment at a scope (e.g. when an institution is removed)."""
    user_ids = list(
        RoleAssignment.objects.active()
        .filter(scope_type=scope.type, scope_id=scope.id)
        .values_list("user_id", flat=True)
    )
    count = (
        RoleAssignment.objects.active()
        .filter(scope_type=scope.type, scope_id=scope.id)
        .update(revoked_at=timezone.now())
    )
    for user_id in set(user_ids):
        invalidate_user_permissions(user_id)
    return count


def sync_system_roles() -> int:
    """Create/update system roles declared by installed modules."""
    count = 0
    for definition in registry.roles.values():
        Role.objects.update_or_create(
            key=definition.key,
            defaults={
                "name": definition.name,
                "description": definition.description,
                "scope_type": definition.scope_type,
                "permissions": list(definition.permissions),
                "is_system": True,
            },
        )
        count += 1
    invalidate_all_permissions()
    return count
