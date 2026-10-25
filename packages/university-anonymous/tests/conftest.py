import datetime as dt

import pytest
from django.utils import timezone

from tests.audience.apps import MEMBERS
from university.core.testing import *  # noqa: F403
from university.core.testing import create_user
from university.permissions.models import Role
from university.permissions.services import assign_role

INSTITUTION = "inst-1"


def veteran(email, handle, *, member=True):
    user = create_user(email, handle=handle)
    type(user).objects.filter(pk=user.pk).update(created_at=timezone.now() - dt.timedelta(days=30))
    user.refresh_from_db()
    if member:
        MEMBERS.setdefault(str(user.pk), []).append(("institution", INSTITUTION))
    return user


@pytest.fixture(autouse=True)
def _reset_members():
    MEMBERS.clear()
    yield
    MEMBERS.clear()


@pytest.fixture
def author(db):
    return veteran("author@example.com", "secretauthor")


@pytest.fixture
def reader(db):
    return veteran("reader@example.com", "reader")


@pytest.fixture
def outsider(db):
    return veteran("outsider@example.com", "outsider", member=False)


@pytest.fixture
def moderator(db):
    mod = veteran("mod@example.com", "moderator1")
    assign_role(user=mod, role_key="platform_moderator")
    return mod


@pytest.fixture
def second_moderator(db):
    mod = veteran("mod2@example.com", "moderator2")
    assign_role(user=mod, role_key="platform_moderator")
    return mod


@pytest.fixture
def revealer(db):
    user = veteran("legal@example.com", "legalofficer")
    Role.objects.get_or_create(
        key="reveal_requester", defaults={"name": "x", "permissions": ["anonymous.identity.reveal"]}
    )
    assign_role(user=user, role_key="reveal_requester")
    return user


@pytest.fixture
def approver(db):
    user = veteran("dpo@example.com", "dpo")
    Role.objects.get_or_create(
        key="reveal_approver", defaults={"name": "x", "permissions": ["anonymous.identity.reveal_approve"]}
    )
    assign_role(user=user, role_key="reveal_approver")
    return user
