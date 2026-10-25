"""Example University deployment.

Demonstrates how a project composes University Core with optional modules.
All secrets and environment-specific values come from environment variables
(see ``.env.example``); nothing sensitive is committed.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from urllib.parse import urlparse

from university.core import CORE_APPS
from university.core.api.schema import spectacular_settings
from university.core.settings import (
    email_settings,
    logging_settings,
    production_security_settings,
    recommended_middleware,
    rest_framework_settings,
)

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me" if DEBUG else None)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")

# ------------------------------------------------------------------ apps
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    # Level one: University Core (core, audit, users, security, permissions).
    *CORE_APPS,
    # Level two: optional modules. Add or remove freely.
    "university.institution",
    "university.social",
    "university.moderation",
    "university.anonymous",  # requires university.moderation
    "university.community",
    "university.notifications",
    "university.events",
    "university.creator",
    "university.payments",
    "university.marketplace",
    "university.media",
    "university.podcast",
    "university.analytics",
    "university.trending",
    "university.search",
]

CORS_ENABLED = env_bool("CORS_ENABLED", False)
if CORS_ENABLED:
    INSTALLED_APPS.append("corsheaders")
    CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")  # never "allow all"
    CORS_ALLOW_CREDENTIALS = True

MIDDLEWARE = recommended_middleware(cors=CORS_ENABLED)
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# -------------------------------------------------------------- database
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    parsed = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or 5432),
            "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

# ----------------------------------------------------------------- cache
REDIS_URL = os.environ.get("REDIS_URL")
CACHES = {
    "default": (
        {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
        if REDIS_URL
        else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    )
}

# ------------------------------------------------------------------ auth
AUTH_USER_MODEL = "university_users.User"
AUTHENTICATION_BACKENDS = ["university.users.backends.UniversityAuthBackend"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
if importlib.util.find_spec("argon2") is not None:  # pip install 'university-core[argon2]'
    PASSWORD_HASHERS.insert(0, "django.contrib.auth.hashers.Argon2PasswordHasher")
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ------------------------------------------------------------------- API
REST_FRAMEWORK = rest_framework_settings()
SPECTACULAR_SETTINGS = spectacular_settings(
    TITLE="University API (example)",
    ENUM_NAME_OVERRIDES={
        **spectacular_settings()["ENUM_NAME_OVERRIDES"],
        "MembershipStatusEnum": "university.institution.constants.MembershipStatus",
        "VerificationStatusEnum": "university.institution.constants.VerificationStatus",
        "InstitutionStatusEnum": "university.institution.constants.InstitutionStatus",
        "SocialVisibilityEnum": "university.social.constants.Visibility",
        "ContentStatusEnum": "university.social.constants.ContentStatus",
        "CaseStatusEnum": "university.moderation.constants.CaseStatus",
        "ModerationActionEnum": "university.moderation.constants.Action",
        "AppealStatusEnum": "university.moderation.constants.AppealStatus",
        "SeverityEnum": "university.moderation.constants.Severity",
        "CommunityPrivacyEnum": "university.community.constants.Privacy",
        "CommunityStatusEnum": "university.community.constants.CommunityStatus",
        "CommunityRoleEnum": "university.community.constants.Role",
        "CommunityMembershipStatusEnum": "university.community.constants.MembershipStatus",
        "EventStatusEnum": "university.events.constants.EventStatus",
        "AudienceVisibilityEnum": "university.events.constants.EventVisibility",
        "EventRegistrationStatusEnum": "university.events.constants.RegistrationStatus",
        "CreatorVerificationStatusEnum": "university.creator.constants.VerificationStatus",
        "CreatorRequestStatusEnum": "university.creator.constants.RequestStatus",
        "CreatorProfileStatusEnum": "university.creator.constants.ProfileStatus",
        "CampaignStatusEnum": "university.creator.constants.CampaignStatus",
        "CampaignVisibilityEnum": "university.creator.constants.CampaignVisibility",
        "ParticipationStatusEnum": "university.creator.constants.ParticipationStatus",
        "DeliverableStatusEnum": "university.creator.constants.DeliverableStatus",
        "MediaKitVisibilityEnum": "university.creator.constants.KitVisibility",
        "ListingVisibilityEnum": "university.marketplace.constants.ListingVisibility",
        "DisputeOutcomeEnum": "university.marketplace.constants.DisputeOutcome",
        "MarketOrderStatusEnum": "university.marketplace.constants.OrderStatus",
        "PaymentIntentStatusEnum": "university.payments.constants.IntentStatus",
        "PayoutStatusEnum": "university.payments.constants.PayoutStatus",
        "RefundStatusEnum": "university.payments.constants.RefundStatus",
        "MediaKindEnum": "university.media.models.AssetKind",
        "MediaStatusEnum": "university.media.models.AssetStatus",
        "TranscriptFormatEnum": "university.podcast.constants.TranscriptFormat",
        "EventFormatEnum": "university.events.constants.EventFormat",
        "PodcastStatusEnum": "university.podcast.constants.ShowStatus",
        "EpisodeStatusEnum": "university.podcast.constants.EpisodeStatus",
    },
)

# ------------------------------------------------------------ University
UNIVERSITY = {
    "AUTH": {
        "JWT": {"SIGNING_KEY": os.environ.get("JWT_SIGNING_KEY")},
    },
    "SECURITY": {
        "HMAC_KEY": os.environ.get("UNIVERSITY_HMAC_KEY"),
        "TRUSTED_PROXY_COUNT": int(os.environ.get("TRUSTED_PROXY_COUNT", "0")),
    },
    "USERS": {
        "FRONTEND_URLS": {
            "VERIFY_EMAIL": env("FRONTEND_URL", "http://localhost:3000") + "/verify-email?token={token}",
            "CONFIRM_EMAIL_CHANGE": env("FRONTEND_URL", "http://localhost:3000") + "/confirm-email?token={token}",
            "RESET_PASSWORD": env("FRONTEND_URL", "http://localhost:3000") + "/reset-password?uid={uid}&token={token}",
        },
    },
    "TASKS": {
        "BACKEND": (
            "university.core.tasks.CeleryTaskBackend"
            if os.environ.get("CELERY_BROKER_URL")
            else "university.core.tasks.ImmediateTaskBackend"
        ),
    },
    "PROVIDERS": {
        # e.g. "university.core.providers.sms.TermiiSMSProvider"
        "SMS": os.environ.get("SMS_PROVIDER", "university.core.providers.sms.ConsoleSMSProvider"),
        "SMS_OPTIONS": (
            {"api_key": os.environ["SMS_API_KEY"], "sender_id": os.environ.get("SMS_SENDER_ID", "University")}
            if os.environ.get("SMS_API_KEY")
            else {}
        ),
    },
    "INSTITUTION": {
        "ALLOW_MULTIPLE_INSTITUTIONS": True,
    },
    "ANONYMOUS": {
        # Dedicated Fernet key(s), kept outside the database (first encrypts, all decrypt).
        "IDENTITY_KEYS": env_list("ANONYMOUS_IDENTITY_KEYS"),
    },
}

# ----------------------------------------------------------------- Celery
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL")
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BEAT_SCHEDULE = {
    "university-retention": {
        "task": "university.core.run_task",
        "schedule": 60 * 60 * 6,
        "args": ["university.core.purge", [], {}],
    },
}

# ------------------------------------------------------------------ email
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "University <no-reply@example.com>")
globals().update(email_settings(os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")))

# ---------------------------------------------------------------- storage
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    # Use object storage (S3/MinIO/Cloudinary via django-storages) in production.
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": BASE_DIR / "media"}},
    "private": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": BASE_DIR / "private-media", "base_url": "/private/"},
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

LANGUAGE_CODE = "en"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGGING = logging_settings(level=os.environ.get("LOG_LEVEL", "INFO"), json=not DEBUG)

if not DEBUG:
    globals().update(production_security_settings())
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if env_bool("BEHIND_TLS_PROXY", True) else None
    CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
