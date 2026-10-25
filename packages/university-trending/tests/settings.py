from university.core import CORE_APPS
from university.core.testing import build_test_settings

globals().update(
    build_test_settings(
        installed_apps=["drf_spectacular", *CORE_APPS, "university.trending", "tests.content", "tests.audience"],
        root_urlconf="tests.urls",
        UNIVERSITY={
            "TRENDING": {
                "SIGNALS": {
                    "test.item.liked": {"content_type": "test.item", "id_key": "item_id", "signal": "reaction"},
                    "test.item.shared": {"content_type": "test.item", "id_key": "item_id", "signal": "share"},
                }
            }
        },
    )
)
