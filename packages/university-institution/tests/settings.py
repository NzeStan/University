from university.core import CORE_APPS
from university.core.testing import build_test_settings

globals().update(
    build_test_settings(
        installed_apps=["drf_spectacular", *CORE_APPS, "university.institution"],
        root_urlconf="tests.urls",
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
            "private": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        },
    )
)

from university.core.api.schema import spectacular_settings  # noqa: E402

SPECTACULAR_SETTINGS = spectacular_settings(
    ENUM_NAME_OVERRIDES={
        **spectacular_settings()["ENUM_NAME_OVERRIDES"],
        "MembershipStatusEnum": "university.institution.constants.MembershipStatus",
        "VerificationStatusEnum": "university.institution.constants.VerificationStatus",
        "InstitutionStatusEnum": "university.institution.constants.InstitutionStatus",
    }
)
