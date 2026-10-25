import pytest

from university.core.registry import registry
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db
URL = "/api/v1/__module__/items/"


def test_module_is_registered():
    assert registry.is_installed("__module__")
    assert "__module__.items.create" in registry.permissions


def test_create_requires_permission(auth_client, user, superuser):
    assert auth_client(user).post(URL, {"title": "x"}, format="json").status_code == 403
    response = auth_client(superuser).post(URL, {"title": "First"}, format="json")
    assert response.status_code == 201
    assert auth_client(superuser).get(URL).json()["results"][0]["title"] == "First"


@pytest.mark.security
def test_cannot_delete_another_users_item(auth_client, user, superuser):
    item = auth_client(superuser).post(URL, {"title": "Mine"}, format="json").json()
    assert auth_client(user).delete(f"{URL}{item['id']}/").status_code == 404


def test_mass_assignment_ignored(auth_client, superuser, user):
    response = auth_client(superuser).post(URL, {"title": "x", "owner": str(user.pk)}, format="json")
    assert response.status_code == 201
    assert auth_client(user).get(URL).json()["results"] == []


def test_role_based_access(auth_client, user):
    from university.permissions.models import Role

    Role.objects.create(key="item_creator", name="Item creator", permissions=["__module__.items.create"])
    assign_role(user=user, role_key="item_creator")
    assert auth_client(user).post(URL, {"title": "Allowed"}, format="json").status_code == 201
