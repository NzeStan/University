"""Versioned API URL composition.

Builds ``/<API.URL_PREFIX>/<version>/`` routes from every installed
University module's ``api_urlconfs``. Adding a module to ``INSTALLED_APPS`` is
enough to mount its API — Core never lists modules explicitly.

Each version is a URL namespace (``v1``), used by DRF's
``NamespaceVersioning`` to populate ``request.version``. A module's own
``app_name`` nests inside it, e.g. ``reverse("v1:users:me")``.
"""

from __future__ import annotations

from django.urls import URLPattern, URLResolver, include, path

from university.core.conf import university_settings
from university.core.registry import registry


def version_patterns(version: str) -> list[URLPattern | URLResolver]:
    patterns: list[URLPattern | URLResolver] = []
    for config in registry.configs():
        urlconf = config.get_api_urlconf(version)
        if urlconf:
            patterns.append(path(config.api_prefix, include(urlconf)))
    return patterns


def build_api_urlpatterns() -> list[URLPattern | URLResolver]:
    patterns: list[URLPattern | URLResolver] = []
    for version in university_settings.get("API.ALLOWED_VERSIONS", ["v1"]):
        patterns.append(path(f"{version}/", include((version_patterns(version), version), namespace=version)))
    return patterns


urlpatterns = build_api_urlpatterns()
