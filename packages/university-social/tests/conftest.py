import pytest

from tests.audience.apps import MEMBERS
from university.core.testing import *  # noqa: F403
from university.core.testing import create_user


@pytest.fixture(autouse=True)
def _reset_audiences():
    MEMBERS.clear()
    yield
    MEMBERS.clear()


@pytest.fixture
def third_user(db):
    return create_user("ngozi@example.com", handle="ngozi")
