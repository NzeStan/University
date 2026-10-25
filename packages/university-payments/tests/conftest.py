import pytest

from tests.shop.apps import ITEMS, PAID, REFUNDED
from university.core.testing import *  # noqa: F403
from university.payments.providers import reset_providers
from university.payments.providers import testing as gateway


@pytest.fixture(autouse=True)
def _payments(settings):
    for store in (ITEMS, PAID, REFUNDED):
        store.clear()
    gateway.reset()
    reset_providers()
    settings.UNIVERSITY = {
        "PAYMENTS": {
            "PROVIDERS": {"test": {"class": "university.payments.providers.testing.TestPaymentProvider"}},
            "DEFAULT_PROVIDER": "test",
        }
    }
    yield
    gateway.reset()
