from university.core import CORE_APPS
from university.core.testing import build_test_settings

globals().update(
    build_test_settings(
        # Core + social only: proves social has no dependency on other modules.
        installed_apps=["drf_spectacular", *CORE_APPS, "university.social", "tests.audience"],
        root_urlconf="tests.urls",
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        },
    )
)
