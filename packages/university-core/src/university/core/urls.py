"""Root URLs for a University deployment.

Include once in the project URLconf::

    urlpatterns = [
        path("admin/", admin.site.urls),
        path("", include("university.core.urls")),
    ]

This mounts ``/health/…``, the versioned API under ``/api/`` and — when
drf-spectacular is installed — ``/api/schema/`` and ``/api/docs/``.
Use :data:`health_urlpatterns` or :data:`api_urlpatterns` individually for
finer control.
"""

from __future__ import annotations

from django.urls import URLPattern, URLResolver, include, path

from university.core import health
from university.core.api.schema import SPECTACULAR_INSTALLED
from university.core.conf import university_settings

health_urlpatterns: list[URLPattern | URLResolver] = [
    path("health/", health.health, name="university-health"),
    path("health/live/", health.live, name="university-health-live"),
    path("health/ready/", health.ready, name="university-health-ready"),
]

_prefix = str(university_settings.get("API.URL_PREFIX", "api")).strip("/")

api_urlpatterns: list[URLPattern | URLResolver] = [
    path(f"{_prefix}/", include("university.core.api.urls")),
]

schema_urlpatterns: list[URLPattern | URLResolver] = []
if SPECTACULAR_INSTALLED and university_settings.get("API.SCHEMA_ENABLED", True):
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

    schema_urlpatterns.append(path(f"{_prefix}/schema/", SpectacularAPIView.as_view(), name="university-schema"))
    if university_settings.get("API.DOCS_ENABLED", True):
        schema_urlpatterns.append(
            path(
                f"{_prefix}/docs/",
                SpectacularSwaggerView.as_view(url_name="university-schema"),
                name="university-docs",
            )
        )

urlpatterns = [*health_urlpatterns, *schema_urlpatterns, *api_urlpatterns]
