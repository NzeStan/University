from university.core import CORE_APPS
from university.core.testing import build_test_settings

globals().update(
    build_test_settings(
        # Core + moderation + a stand-in content module: no dependency on social.
        installed_apps=["drf_spectacular", *CORE_APPS, "university.moderation", "tests.notes"],
        root_urlconf="tests.urls",
    )
)
