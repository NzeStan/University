from university.core import CORE_APPS
from university.core.testing import build_test_settings

globals().update(
    build_test_settings(
        installed_apps=["drf_spectacular", *CORE_APPS, "university.payments", "tests.shop"],
        root_urlconf="tests.urls",
    )
)
