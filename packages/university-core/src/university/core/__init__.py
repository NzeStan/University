"""University Core — the foundation of the University platform.

University Core is the *level one* package of the University platform. It
ships the Django apps that almost every installation needs:

* ``university.core``        — base models, settings, registry, events, tasks,
                                 providers, API infrastructure, health checks.
* ``university.users``       — the custom user model, accounts and preferences.
* ``university.security``    — authentication, sessions, tokens, API keys, OTP.
* ``university.permissions`` — scoped role-based access control.
* ``university.audit``       — append-only, tamper-evident audit logging.

Optional features live in independently installable *level two* packages
(``university-institution``, ``university-social`` …) that plug into Core
through the module registry, events and hooks.
"""

__version__ = "0.1.0"

#: The Django apps that make up University Core, in dependency order.
#: Use as ``INSTALLED_APPS = [..., *CORE_APPS, ...]``.
CORE_APPS: list[str] = [
    "university.core",
    "university.audit",
    "university.users",
    "university.security",
    "university.permissions",
]

__all__ = ["CORE_APPS", "__version__"]
