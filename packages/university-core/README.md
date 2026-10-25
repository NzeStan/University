# university-core

**The secure, modular foundation of the University platform**: a Django REST Framework
platform for African campus ecosystems (Nigeria-first, Africa-ready).

`university-core` is the *level one* package. It provides five Django apps that nearly every
installation needs:

| App | Provides |
| --- | --- |
| `university.core` | UUID base models, soft deletion, namespaced settings, module registry and plugins, event bus, hooks, task abstraction, provider adapters (email, SMS, search, anti-spam), distributed rate limiting, idempotency, signed webhooks, secure uploads, health checks, structured logging, versioned API infrastructure, system checks, data retention |
| `university.users` | Swappable custom user model, accounts, verification, privacy/notification/security settings, consent, data export, soft deletion with anonymisation |
| `university.security` | JWT access tokens + rotating refresh tokens with reuse detection, sessions/devices, scoped API keys, lockout, suspicious-login alerts, OTP, MFA, passwordless, OIDC |
| `university.permissions` | Scoped RBAC with hierarchy resolution and privilege-escalation protection |
| `university.audit` | Append-only, HMAC-signed audit log |

Optional features come from *level two* packages such as
[`university-institution`](https://pypi.org/project/university-institution/).

## Install

```bash
pip install "university-core[postgres,redis,celery,openapi,argon2]"
```

```python
from university.core import CORE_APPS
from university.core.settings import recommended_middleware, rest_framework_settings

INSTALLED_APPS = [..., "rest_framework", *CORE_APPS]
MIDDLEWARE = recommended_middleware()
REST_FRAMEWORK = rest_framework_settings()
AUTH_USER_MODEL = "university_users.User"
AUTHENTICATION_BACKENDS = ["university.users.backends.UniversityAuthBackend"]
```

```python
urlpatterns = [path("", include("university.core.urls"))]  # /health/, /api/v1/, /api/docs/
```

Supported versions: Python 3.11–3.14; Django 5.2, 6.0, 6.1; DRF 3.15+.

Documentation, security policy and source: https://github.com/NzeStan/University
