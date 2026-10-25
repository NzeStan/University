import pytest

from tests.content.apps import BLOCKS, ITEMS
from university.core.testing import *  # noqa: F403
from university.core.testing import create_user


@pytest.fixture(autouse=True)
def _reset_content():
    ITEMS.clear()
    BLOCKS.clear()
    yield
    ITEMS.clear()
    BLOCKS.clear()


@pytest.fixture
def third_user(db):
    return create_user("ngozi@example.com", handle="ngozi")
