from __future__ import annotations

from typing import Any

from django.contrib.auth.base_user import BaseUserManager
from django.db import models

from university.users.constants import UserStatus
from university.users.validators import normalize_email, normalize_handle


class UserQuerySet(models.QuerySet):
    def active(self) -> UserQuerySet:
        return self.filter(status=UserStatus.ACTIVE)

    def not_deleted(self) -> UserQuerySet:
        return self.exclude(status=UserStatus.DELETED)


class UserManager(BaseUserManager.from_queryset(UserQuerySet)):  # type: ignore[misc]
    """Default manager. Soft-deleted users are excluded unless ``include_deleted``."""

    use_in_migrations = True

    def __init__(self, *, include_deleted: bool = False) -> None:
        super().__init__()
        self.include_deleted = include_deleted

    def deconstruct(self) -> tuple[bool, str | None, str | None, tuple[Any, ...], dict[str, Any]]:
        as_manager, _manager_class, qs_class, args, kwargs = super().deconstruct()
        return as_manager, "university.users.managers.UserManager", qs_class, args, kwargs

    def get_queryset(self) -> UserQuerySet:
        qs = super().get_queryset()
        return qs if self.include_deleted else qs.filter(deleted_at__isnull=True)

    def get_by_natural_key(self, username: str) -> Any:
        return self.get(**{self.model.USERNAME_FIELD: normalize_email(username)})

    def _create_user(self, email: str, password: str | None, **extra: Any) -> Any:
        if not email:
            raise ValueError("Users must have an email address.")
        extra["handle"] = normalize_handle(extra.get("handle"))
        user = self.model(email=normalize_email(email), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.full_clean(exclude=["password"], validate_unique=False, validate_constraints=False)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra: Any) -> Any:
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        extra.setdefault("status", UserStatus.ACTIVE)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> Any:
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("status", UserStatus.ACTIVE)
        if extra["is_staff"] is not True or extra["is_superuser"] is not True:
            raise ValueError("Superusers must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra)
