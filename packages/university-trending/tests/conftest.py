import pytest

from tests.content.apps import BLOCKS, ITEMS
from university.core.testing import *  # noqa: F403


@pytest.fixture(autouse=True)
def _reset_content():
    ITEMS.clear()
    BLOCKS.clear()
    yield
    ITEMS.clear()
