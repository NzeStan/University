"""Health check endpoints.

* ``/health/``       — liveness summary (cheap; no dependencies touched).
* ``/health/live/``  — the process is up.
* ``/health/ready/`` — required dependencies (database, cache, and any
  module-registered checks) are reachable; returns 503 otherwise.

Responses contain only check names and ``ok``/``fail`` — never hostnames,
versions or error messages.
"""

from __future__ import annotations

import logging
import uuid

from django.core.cache import caches
from django.db import connections
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from university.core.conf import university_settings
from university.core.declarations import HealthCheck
from university.core.registry import registry

logger = logging.getLogger("university.health")


def check_database() -> bool:
    for alias in connections:
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    return True


def check_cache() -> bool:
    cache = caches[university_settings.get("CACHE.ALIAS", "default")]
    key = f"{university_settings.get('CACHE.KEY_PREFIX', 'university')}:health:{uuid.uuid4().hex}"
    cache.set(key, "1", timeout=5)
    ok = cache.get(key) == "1"
    cache.delete(key)
    return ok


BUILTIN_CHECKS = {
    "database": HealthCheck("database", check_database),
    "cache": HealthCheck("cache", check_cache),
}


def run_readiness_checks() -> tuple[bool, dict[str, str]]:
    available = {**BUILTIN_CHECKS, **registry.health_checks}
    names = university_settings.get("HEALTH.READINESS_CHECKS", ["database", "cache"])
    names = list(dict.fromkeys([*names, *registry.health_checks]))
    results: dict[str, str] = {}
    healthy = True
    for name in names:
        check = available.get(name)
        if check is None:
            continue
        try:
            ok = check.check() is not False
        except Exception:
            logger.exception("Readiness check %s failed", name)
            ok = False
        results[name] = "ok" if ok else "fail"
        if not ok and check.critical:
            healthy = False
    return healthy, results


@never_cache
@require_GET
def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@never_cache
@require_GET
def live(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@never_cache
@require_GET
def ready(request: HttpRequest) -> JsonResponse:
    healthy, results = run_readiness_checks()
    return JsonResponse(
        {"status": "ok" if healthy else "unavailable", "checks": results},
        status=200 if healthy else 503,
    )
