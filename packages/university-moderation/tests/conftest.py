import pytest

from university.core.testing import *  # noqa: F403
from university.core.testing import create_user
from university.permissions.services import assign_role


@pytest.fixture
def moderator(db):
    mod = create_user("mod@example.com", handle="moderator1")
    assign_role(user=mod, role_key="platform_moderator")
    return mod


@pytest.fixture
def second_moderator(db):
    mod = create_user("mod2@example.com", handle="moderator2")
    assign_role(user=mod, role_key="platform_moderator")
    return mod


@pytest.fixture
def note(user):
    from tests.notes.models import Note

    return Note.objects.create(author=user, body="Offensive text")


@pytest.fixture
def anon_note(user):
    from tests.notes.models import Note

    return Note.objects.create(author=user, body="Anonymous rant", anonymous=True)


@pytest.fixture
def third_party(db):
    return create_user("ngozi@example.com", handle="ngozi")
