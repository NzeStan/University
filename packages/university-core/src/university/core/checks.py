"""Django system checks for University deployments.

Run ``manage.py check`` (and ``manage.py check --deploy`` before releasing).
Checks tagged ``deploy`` only fire under ``--deploy``.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

from university.core.conf import SETTINGS_NAME, get_user_settings
from university.core.defaults import DEFAULTS
from university.core.registry import registry

UNIVERSITY_TAG = "university"


@register(UNIVERSITY_TAG)
def check_module_dependencies(app_configs: Any = None, **kwargs: Any) -> list[Error]:
    return [
        Error(
            f"University module {module!r} requires {', '.join(repr(m) for m in missing)}.",
            hint="Install the missing package(s) and add them to INSTALLED_APPS.",
            id="university.E001",
        )
        for module, missing in registry.missing_dependencies().items()
    ]


@register(UNIVERSITY_TAG)
def check_user_model(app_configs: Any = None, **kwargs: Any) -> list[Error]:
    from django.contrib.auth import get_user_model

    if not registry.is_installed("users"):
        return []
    from university.users.models import AbstractUniversityUser

    model = get_user_model()
    if not issubclass(model, AbstractUniversityUser):
        return [
            Error(
                "AUTH_USER_MODEL must subclass university.users.models.AbstractUniversityUser.",
                hint='Set AUTH_USER_MODEL = "university_users.User" or subclass AbstractUniversityUser.',
                id="university.E002",
            )
        ]
    return []


@register(UNIVERSITY_TAG)
def check_settings_keys(app_configs: Any = None, **kwargs: Any) -> list[Warning]:
    known = set(DEFAULTS) | {m.name.upper() for m in registry.all()}
    known |= {getattr(c, "settings_namespace", None) or "" for c in registry.configs()}
    return [
        Warning(
            f"Unknown key {key!r} in settings.{SETTINGS_NAME}.",
            hint="Check for typos or a module that is not installed.",
            id="university.W001",
        )
        for key in get_user_settings()
        if key not in known
    ]


@register(UNIVERSITY_TAG)
def check_drf_integration(app_configs: Any = None, **kwargs: Any) -> list[Warning]:
    drf = getattr(settings, "REST_FRAMEWORK", {}) or {}
    issues: list[Warning] = []
    if drf.get("EXCEPTION_HANDLER") != "university.core.api.exceptions.exception_handler":
        issues.append(
            Warning(
                "REST_FRAMEWORK['EXCEPTION_HANDLER'] is not the University handler; "
                "error responses will not use the standard envelope.",
                hint="Use university.core.settings.rest_framework_settings().",
                id="university.W002",
            )
        )
    middleware = list(getattr(settings, "MIDDLEWARE", []))
    if "university.core.middleware.RequestContextMiddleware" not in middleware:
        issues.append(
            Warning(
                "RequestContextMiddleware is not installed; request ids and audit context are missing.",
                id="university.W003",
            )
        )
    return issues


@register(UNIVERSITY_TAG)
def check_content_adapters(app_configs: Any = None, **kwargs: Any) -> list[Error]:
    """Moderatable adapters must implement the state changes moderation applies."""
    from university.core.content import ContentAdapter

    issues = []
    for content_type, adapter in registry.content_adapters.items():
        if not getattr(adapter, "moderatable", False):
            continue
        missing = [m for m in ("hide", "restore", "remove") if getattr(type(adapter), m) is getattr(ContentAdapter, m)]
        if missing:
            issues.append(
                Error(
                    f"Content adapter {content_type!r} is moderatable but doesn't implement {', '.join(missing)}.",
                    hint="Implement them, or set moderatable = False if the type shouldn't be reportable.",
                    id="university.E003",
                )
            )
    return issues


@register(UNIVERSITY_TAG, Tags.security, deploy=True)
def check_production_settings(app_configs: Any = None, **kwargs: Any) -> list[Error | Warning]:
    from django.core.files.storage import storages

    from university.core.conf import university_settings

    issues: list[Error | Warning] = []
    cache_backend = settings.CACHES.get(university_settings.get("CACHE.ALIAS", "default"), {}).get("BACKEND", "")
    if cache_backend.endswith(("LocMemCache", "DummyCache")):
        issues.append(
            Warning(
                "The University cache is process-local; rate limits, lockouts and permission "
                "caches will not be shared between servers.",
                hint="Use Redis (django.core.cache.backends.redis.RedisCache).",
                id="university.W010",
            )
        )
    if getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False) or getattr(settings, "CORS_ORIGIN_ALLOW_ALL", False):
        issues.append(
            Error(
                "CORS allows all origins.",
                hint="List trusted origins in CORS_ALLOWED_ORIGINS.",
                id="university.E011",
            )
        )
    if not university_settings.get("AUTH.JWT.SIGNING_KEY") and university_settings.get(
        "AUTH.JWT.ALGORITHM", "HS256"
    ).startswith("HS"):
        issues.append(
            Warning(
                "JWTs are signed with a key derived from SECRET_KEY.",
                hint="Set UNIVERSITY['AUTH']['JWT']['SIGNING_KEY'] to a dedicated secret.",
                id="university.W012",
            )
        )
    if university_settings.get("TASKS.BACKEND", "").endswith("ImmediateTaskBackend"):
        issues.append(
            Warning(
                "Tasks run synchronously inside requests.",
                hint="Use CeleryTaskBackend or DjangoTaskBackend in production.",
                id="university.W013",
            )
        )
    if university_settings.get("PROVIDERS.SMS", "").endswith("ConsoleSMSProvider"):
        issues.append(
            Warning(
                "The console SMS provider does not deliver messages.",
                hint="Configure a real SMS provider (Termii, Twilio, Africa's Talking …).",
                id="university.W014",
            )
        )
    try:
        default_storage_backend = storages.backends.get("default", {}).get("BACKEND", "")
    except Exception:  # pragma: no cover
        default_storage_backend = ""
    if default_storage_backend.endswith("FileSystemStorage"):
        issues.append(
            Warning(
                "User media is stored on the local filesystem.",
                hint="Use object storage (S3, MinIO, Cloudinary …) for production media.",
                id="university.W015",
            )
        )
    return issues
