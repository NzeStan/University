"""Test utilities for University and for authors of University modules.

Use from a module's ``conftest.py``::

    from university.core.testing import *  # noqa: F403  (fixtures)

Fixtures: ``api_client``, ``user``, ``other_user``, ``staff_user``,
``superuser``, ``auth_client`` (factory), ``outbox``.
Helpers: :func:`create_user`, :func:`authenticate`, :func:`build_test_settings`.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

PASSWORD = "Correct-Horse-Battery-9"


def build_test_settings(*, installed_apps: list[str], root_urlconf: str, **overrides: Any) -> dict[str, Any]:
    """Minimal, fast settings for testing a University module in isolation.

    Uses SQLite by default; set ``UNIVERSITY_TEST_DB=postgres`` (with the
    standard ``PG*`` environment variables) to run against PostgreSQL.
    """
    from university.core.settings import email_settings, rest_framework_settings

    if os.environ.get("UNIVERSITY_TEST_DB") == "postgres":
        database = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("PGDATABASE", "university"),
            "USER": os.environ.get("PGUSER", "postgres"),
            "PASSWORD": os.environ.get("PGPASSWORD", "postgres"),
            "HOST": os.environ.get("PGHOST", "localhost"),
            "PORT": os.environ.get("PGPORT", "5432"),
        }
    else:
        database = {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
    settings: dict[str, Any] = {
        "SECRET_KEY": "test-only-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz",
        "DEBUG": False,
        "ALLOWED_HOSTS": ["*"],
        "USE_TZ": True,
        "TIME_ZONE": "UTC",
        "INSTALLED_APPS": [
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.messages",
            "rest_framework",
            *installed_apps,
        ],
        "MIDDLEWARE": [
            "django.middleware.security.SecurityMiddleware",
            "university.core.middleware.RequestContextMiddleware",
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.common.CommonMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
            "university.core.middleware.APISecurityHeadersMiddleware",
        ],
        "ROOT_URLCONF": root_urlconf,
        "DATABASES": {"default": database},
        "CACHES": {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        "AUTH_USER_MODEL": "university_users.User",
        "AUTHENTICATION_BACKENDS": ["university.users.backends.UniversityAuthBackend"],
        "PASSWORD_HASHERS": ["django.contrib.auth.hashers.MD5PasswordHasher"],
        "AUTH_PASSWORD_VALIDATORS": [
            {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
            {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
            {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
            {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
        ],
        **email_settings("django.core.mail.backends.locmem.EmailBackend"),
        "DEFAULT_FROM_EMAIL": "no-reply@example.test",
        "TEMPLATES": [
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
                "OPTIONS": {
                    "context_processors": [
                        "django.template.context_processors.request",
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    ]
                },
            }
        ],
        "REST_FRAMEWORK": rest_framework_settings(),
        "DEFAULT_AUTO_FIELD": "django.db.models.BigAutoField",
        "UNIVERSITY": {
            "TASKS": {"EAGER_PROPAGATE_EXCEPTIONS": True},
            "EVENTS": {"RAISE_HANDLER_ERRORS": True},
            "PLUGINS": {"LOAD_ENTRY_POINTS": False},
        },
    }
    settings.update(overrides)
    return settings


def create_user(
    email: str = "ada@example.com",
    password: str = PASSWORD,
    *,
    handle: str | None = None,
    verified: bool = True,
    **extra: Any,
) -> Any:
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from university.users.services import ensure_user_settings

    if verified:
        extra.setdefault("email_verified_at", timezone.now())
    user = get_user_model().objects.create_user(email=email, password=password, handle=handle, **extra)
    ensure_user_settings(user)
    return user


def authenticate(client: Any, user: Any, *, device_id: str = "test-device") -> dict[str, Any]:
    """Sign ``user`` in through the security service and attach the bearer token."""
    from university.core.http import ClientMeta
    from university.security.services.sessions import create_session

    _, tokens = create_session(
        user, meta=ClientMeta(ip_address="127.0.0.1", user_agent="pytest", device_id=device_id), auth_method="test"
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens.access}")
    return tokens.as_dict()


@pytest.fixture
def api_client() -> Any:
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def user(db: Any) -> Any:
    return create_user("ada@example.com", handle="ada")


@pytest.fixture
def other_user(db: Any) -> Any:
    return create_user("grace@example.com", handle="grace")


@pytest.fixture
def staff_user(db: Any) -> Any:
    return create_user("staff@example.com", handle="staffer", is_staff=True)


@pytest.fixture
def superuser(db: Any) -> Any:
    from django.contrib.auth import get_user_model

    from university.users.services import ensure_user_settings

    admin = get_user_model().objects.create_superuser(email="root@example.com", password=PASSWORD, handle="rootadmin")
    ensure_user_settings(admin)
    return admin


@pytest.fixture
def auth_client(db: Any) -> Any:
    """Factory: ``auth_client(user)`` returns an authenticated APIClient."""
    from rest_framework.test import APIClient

    def make(user: Any) -> Any:
        client = APIClient()
        authenticate(client, user)
        return client

    return make


@pytest.fixture
def outbox(settings: Any) -> Any:
    from django.core import mail

    mail.outbox = []
    return mail.outbox


@pytest.fixture(autouse=True)
def _university_isolation(request: Any, settings: Any, monkeypatch: Any) -> Any:
    """Fresh cache per test, and on-commit callbacks run immediately.

    pytest-django wraps ordinary tests in a transaction that is rolled back,
    so ``transaction.on_commit`` callbacks (events, emails, tasks) would never
    fire. They run immediately instead, except in ``transaction=True`` tests,
    which exercise real commit semantics.
    """
    from django.core.cache import cache
    from django.db import transaction

    marker = request.node.get_closest_marker("django_db")
    if not (marker and marker.kwargs.get("transaction")):
        monkeypatch.setattr(transaction, "on_commit", lambda func, using=None, robust=False: func())
    cache.clear()
    yield
    cache.clear()


__all__ = [
    "PASSWORD",
    "_university_isolation",
    "api_client",
    "auth_client",
    "authenticate",
    "build_test_settings",
    "create_user",
    "other_user",
    "outbox",
    "staff_user",
    "superuser",
    "user",
]
