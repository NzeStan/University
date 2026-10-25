from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from university.core.declarations import PLATFORM_SCOPE
from university.core.models import BaseModel


class Role(BaseModel):
    """A named bundle of permission codes valid at one scope type.

    ``permissions`` holds permission codes or shell-style patterns
    (``"institution.*"``). System roles are declared by modules in code and
    synchronised on migrate; they cannot be edited through the API.
    """

    key = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    scope_type = models.CharField(max_length=32, default=PLATFORM_SCOPE)
    permissions = models.JSONField(default=list, blank=True)
    is_system = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("role")
        ordering = ("scope_type", "key")

    def __str__(self) -> str:
        return self.name


class RoleAssignmentQuerySet(models.QuerySet):
    def active(self) -> RoleAssignmentQuerySet:
        from django.utils import timezone

        return self.filter(revoked_at__isnull=True).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
        )


class RoleAssignment(BaseModel):
    """Grants a role to a user at a scope (``scope_id`` is ``""`` for platform)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_assignments")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")
    scope_type = models.CharField(max_length=32, default=PLATFORM_SCOPE)
    scope_id = models.CharField(max_length=64, blank=True, default="")
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = RoleAssignmentQuerySet.as_manager()

    class Meta:
        verbose_name = _("role assignment")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role", "scope_type", "scope_id"],
                condition=Q(revoked_at__isnull=True),
                name="univ_perm_assignment_active_unique",
            ),
            models.CheckConstraint(
                condition=(Q(scope_type=PLATFORM_SCOPE) & Q(scope_id=""))
                | (~Q(scope_type=PLATFORM_SCOPE) & ~Q(scope_id="")),
                name="univ_perm_assignment_scope_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "revoked_at"], name="univ_perm_assign_user"),
            models.Index(fields=["scope_type", "scope_id"], name="univ_perm_assign_scope"),
        ]

    def __str__(self) -> str:
        scope = self.scope_type if not self.scope_id else f"{self.scope_type}:{self.scope_id}"
        return f"{self.role.key} @ {scope}"
