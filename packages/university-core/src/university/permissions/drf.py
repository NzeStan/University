"""DRF permission classes backed by the University permission engine.

Examples::

    class AuditLogView(ListAPIView):
        permission_classes = [IsAuthenticated, require_permission("audit.view")]

    class MembershipViewSet(ViewSet):
        # Scope taken from the view: Scope("institution", self.kwargs["institution_id"])
        permission_classes = [IsAuthenticated, require_permission(
            "institution.memberships.verify",
            scope=lambda request, view: Scope("institution", view.kwargs["institution_id"]),
        )]
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rest_framework.permissions import SAFE_METHODS, BasePermission

from university.permissions.scopes import Scope
from university.permissions.services import has_permission

ScopeGetter = Callable[[Any, Any], Scope | None]


def request_api_key(request: Any) -> Any:
    """The APIKey used to authenticate the request, if any."""
    return getattr(getattr(request, "auth", None), "api_key", None)


class HasPermission(BasePermission):
    permission_code: str = ""
    scope_getter: ScopeGetter | None = None
    message = "You do not have permission to perform this action."

    def get_scope(self, request: Any, view: Any) -> Scope | None:
        if self.scope_getter is not None:
            return type(self).scope_getter(request, view)  # type: ignore[misc]
        getter = getattr(view, "get_permission_scope", None)
        return getter() if callable(getter) else None

    def has_permission(self, request: Any, view: Any) -> bool:
        return has_permission(
            request.user, self.permission_code, self.get_scope(request, view), api_key=request_api_key(request)
        )


def require_permission(code: str, *, scope: ScopeGetter | None = None) -> type[HasPermission]:
    """Build a permission class requiring ``code`` (optionally at a scope)."""
    attrs: dict[str, Any] = {"permission_code": code}
    if scope is not None:
        attrs["scope_getter"] = staticmethod(scope)
    return type(f"Requires[{code}]", (HasPermission,), attrs)


class ReadOnly(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return request.method in SAFE_METHODS


class IsOwner(BasePermission):
    """Object-level: ``obj.<owner_field>`` must be the requesting user."""

    owner_field = "user"

    def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
        owner_id = getattr(obj, f"{self.owner_field}_id", None)
        if owner_id is None:
            owner = getattr(obj, self.owner_field, None)
            owner_id = getattr(owner, "pk", None)
        return owner_id is not None and owner_id == request.user.pk


def owned_by(field: str) -> type[IsOwner]:
    return type(f"IsOwner[{field}]", (IsOwner,), {"owner_field": field})


class IsVerifiedEmail(BasePermission):
    message = "Verify your email address to perform this action."

    def has_permission(self, request: Any, view: Any) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and getattr(user, "email_verified_at", None))
