# Installation

## Requirements

| Component | Supported |
| --- | --- |
| Python | 3.11, 3.12, 3.13, 3.14 (Django 6.x requires 3.12+) |
| Django | 5.2 LTS, 6.0, 6.1 |
| Django REST Framework | 3.15+ |
| Database | PostgreSQL 14+ in production; SQLite for development and tests |
| Cache | Redis (required in production for distributed rate limits and lockouts) |
| Task queue | Celery (recommended), Django's built-in tasks (6.0+), or synchronous for development |

## Install packages

```bash
pip install university-core                       # minimal foundation
pip install "university-core[postgres,redis,celery,openapi,argon2]"
pip install university-institution                # optional module
```

Core extras:

| Extra | Adds | Use it for |
| --- | --- | --- |
| `postgres` | psycopg 3 | PostgreSQL |
| `redis` | redis-py | Redis cache / broker |
| `celery` | Celery | background tasks |
| `openapi` | drf-spectacular | `/api/schema/`, `/api/docs/` |
| `argon2` | argon2-cffi | the Argon2 password hasher (recommended) |
| `oidc` | PyJWT[crypto] | OIDC identity providers (RS256/ES256 tokens) |
| `images` | Pillow | image dimension checks on upload |
| `cors` | django-cors-headers | browser clients on other origins |
| `all` | everything above | |

## Compose your project

```python
from university.core import CORE_APPS
from university.core.settings import (
    email_settings,
    logging_settings,
    production_security_settings,
    recommended_middleware,
    rest_framework_settings,
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",  # with the [openapi] extra
    *CORE_APPS,  # university.core, .audit, .users, .security, .permissions
    "university.institution",  # optional — add or remove freely
]

MIDDLEWARE = recommended_middleware(cors=False)
REST_FRAMEWORK = rest_framework_settings()
AUTH_USER_MODEL = "university_users.User"
AUTHENTICATION_BACKENDS = ["university.users.backends.UniversityAuthBackend"]
LOGGING = logging_settings()
globals().update(email_settings("django.core.mail.backends.smtp.EmailBackend"))
```

`CORE_APPS` keeps the five Core apps together, in the right order.

### URLs

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("university.core.urls")),
]
handler404 = "university.core.api.views.json_page_not_found"
handler500 = "university.core.api.views.json_server_error"
```

`university.core.urls` mounts `/health/`, `/health/live/`, `/health/ready/`, `/api/v1/…` (every
installed module) and, when drf-spectacular is installed, `/api/schema/` and `/api/docs/`. Use
`health_urlpatterns`, `api_urlpatterns` or `schema_urlpatterns` individually for finer control.

### Migrate and verify

```bash
python manage.py migrate
python manage.py university_modules --permissions
python manage.py check --deploy
```

## Adding modules later

1. `pip install university-<module>`
2. Add `"university.<module>"` to `INSTALLED_APPS`.
3. `python manage.py migrate`

The module's API routes, permissions, roles, scope types, event handlers, hooks, health checks
and retention policies are picked up automatically. If a module needs another one that isn't
installed, the `university.E001` system check names the missing package.

## Using a custom user model

Subclass the abstract model in your own app, then point `AUTH_USER_MODEL` at it **before the first
migration**:

```python
# accounts/models.py
from university.users.models import AbstractUniversityUser


class User(AbstractUniversityUser):
    student_union_id = models.CharField(max_length=32, blank=True)

    class Meta(AbstractUniversityUser.Meta):
        swappable = "AUTH_USER_MODEL"
```

```python
AUTH_USER_MODEL = "accounts.User"
```

Every University model references `settings.AUTH_USER_MODEL`. The `university.E002` check fails if
the configured model doesn't subclass `AbstractUniversityUser`. For module-specific profile data,
prefer a one-to-one model in your module over widening the user table.
