"""Settings presets for composing a University deployment.

These helpers return plain dicts/lists so a project stays in full control::

    from university.core import CORE_APPS
    from university.core.settings import (
        rest_framework_settings, recommended_middleware, logging_settings,
    )

    INSTALLED_APPS = [..., "rest_framework", *CORE_APPS, "university.institution"]
    MIDDLEWARE = recommended_middleware()
    REST_FRAMEWORK = rest_framework_settings()
    AUTH_USER_MODEL = "university_users.User"
    AUTHENTICATION_BACKENDS = ["university.users.backends.UniversityAuthBackend"]
    LOGGING = logging_settings()
"""

from __future__ import annotations

from typing import Any

from university.core.api.schema import SPECTACULAR_INSTALLED

AUTH_USER_MODEL = "university_users.User"
AUTHENTICATION_BACKENDS = ["university.users.backends.UniversityAuthBackend"]


def rest_framework_settings(**overrides: Any) -> dict[str, Any]:
    """Recommended ``REST_FRAMEWORK`` configuration."""
    config: dict[str, Any] = {
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "university.security.authentication.JWTAuthentication",
            "university.security.authentication.APIKeyAuthentication",
            # Cookie sessions (admin/internal tools); CSRF is enforced.
            "rest_framework.authentication.SessionAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
        "DEFAULT_THROTTLE_CLASSES": [
            "university.core.api.throttling.GlobalRateThrottle",
            "university.core.api.throttling.ScopedRateThrottle",
        ],
        "DEFAULT_PAGINATION_CLASS": "university.core.api.pagination.PageNumberPagination",
        "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.NamespaceVersioning",
        "DEFAULT_VERSION": "v1",
        "ALLOWED_VERSIONS": ["v1"],
        "EXCEPTION_HANDLER": "university.core.api.exceptions.exception_handler",
        "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
        "DEFAULT_PARSER_CLASSES": [
            "rest_framework.parsers.JSONParser",
            "rest_framework.parsers.MultiPartParser",
        ],
        "DEFAULT_FILTER_BACKENDS": [],
        "TEST_REQUEST_DEFAULT_FORMAT": "json",
        "UNICODE_JSON": True,
        "COERCE_DECIMAL_TO_STRING": True,
    }
    if SPECTACULAR_INSTALLED:
        config["DEFAULT_SCHEMA_CLASS"] = "university.core.api.openapi.UniversityAutoSchema"
    config.update(overrides)
    return config


def recommended_middleware(*, cors: bool = False) -> list[str]:
    """Middleware in a safe order. ``cors=True`` adds django-cors-headers."""
    middleware = [
        "django.middleware.security.SecurityMiddleware",
        "university.core.middleware.RequestContextMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
    ]
    if cors:
        middleware.append("corsheaders.middleware.CorsMiddleware")
    middleware += [
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
        "university.core.middleware.APISecurityHeadersMiddleware",
    ]
    return middleware


def logging_settings(level: str = "INFO", *, json: bool = True) -> dict[str, Any]:
    """Structured, redacted logging to stdout (12-factor friendly)."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "context": {"()": "university.core.logging.RequestContextFilter"},
            "redact": {"()": "university.core.logging.RedactingFilter"},
        },
        "formatters": {
            "json": {"()": "university.core.logging.JSONFormatter"},
            "plain": {"format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "filters": ["context", "redact"],
                "formatter": "json" if json else "plain",
            }
        },
        "root": {"handlers": ["console"], "level": level},
        "loggers": {
            "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        },
    }


def email_settings(backend: str, **options: Any) -> dict[str, Any]:
    """Email backend settings for the running Django version.

    Django 6.1 replaced ``EMAIL_BACKEND`` with ``MAILERS``; this returns the
    right shape for either (merge with ``globals().update(...)``).
    """
    import django

    if django.VERSION >= (6, 1):
        return {"MAILERS": {"default": {"BACKEND": backend, **({"OPTIONS": options} if options else {})}}}
    return {"EMAIL_BACKEND": backend}


def production_security_settings() -> dict[str, Any]:
    """Django security settings recommended for production (merge into globals)."""
    return {
        "SECURE_SSL_REDIRECT": True,
        "SECURE_HSTS_SECONDS": 60 * 60 * 24 * 365,
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": True,
        "SECURE_HSTS_PRELOAD": True,
        "SECURE_CONTENT_TYPE_NOSNIFF": True,
        "SECURE_REFERRER_POLICY": "strict-origin-when-cross-origin",
        "SECURE_CROSS_ORIGIN_OPENER_POLICY": "same-origin",
        "SESSION_COOKIE_SECURE": True,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "CSRF_COOKIE_SECURE": True,
        "CSRF_COOKIE_HTTPONLY": True,
        "CSRF_COOKIE_SAMESITE": "Lax",
        "X_FRAME_OPTIONS": "DENY",
    }
