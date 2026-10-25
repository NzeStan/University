from university.core import CORE_APPS
from university.core.testing import build_test_settings

globals().update(
    build_test_settings(
        installed_apps=["drf_spectacular", *CORE_APPS, "university.search", "tests.content", "tests.audience"],
        root_urlconf="tests.urls",
        UNIVERSITY={
            "SEARCH": {
                "SOURCES": {
                    "test.item": {"index": ["test.item.saved"], "remove": ["test.item.removed"], "id_key": "item_id"}
                }
            }
        },
    )
)
