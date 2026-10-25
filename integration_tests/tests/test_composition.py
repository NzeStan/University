"""The platform composed: Core + institution + social installed together.

These tests prove that modules cooperate purely through Core's extension
points (hooks, events, scopes) — neither module imports the other.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command

from university.core.registry import registry
from university.core.testing import create_user
from university.institution import services as institution
from university.institution.models import Campus, Institution, InstitutionMembership, InstitutionType
from university.permissions.scopes import Scope
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db
SOCIAL = "/api/v1/social"


@pytest.fixture
def uni(db):
    return Institution.objects.create(
        name="Example University",
        short_name="EXU",
        slug="exu",
        country="NG",
        type=InstitutionType.objects.get(key="university"),
    )


def verify(user, institution_obj, **extra):
    membership = institution.request_membership(user=user, institution=institution_obj, role="student", **extra)
    InstitutionMembership.objects.filter(pk=membership.pk).update(status="verified")
    return membership


def test_all_modules_registered_without_missing_dependencies():
    assert {"core", "users", "security", "permissions", "audit", "institution", "social"} <= {
        m.name for m in registry.all()
    }
    assert registry.missing_dependencies() == {}


def test_social_does_not_import_institution():
    import pathlib

    import university.social as social_pkg

    source = "\n".join(p.read_text(encoding="utf-8") for p in pathlib.Path(social_pkg.__path__[0]).rglob("*.py"))
    assert "university.institution" not in source


@pytest.mark.security
def test_verified_institution_members_see_institution_posts(auth_client, user, other_user, uni):
    verify(user, uni)
    post = auth_client(user).post(
        f"{SOCIAL}/posts/", {"body": "EXU only", "visibility": "institution", "audience_id": str(uni.pk)}, format="json"
    )
    assert post.status_code == 201
    url = f"{SOCIAL}/posts/{post.json()['id']}/"
    # Not a member yet -> invisible.
    assert auth_client(other_user).get(url).status_code == 404
    # A pending membership is not enough.
    membership = institution.request_membership(user=other_user, institution=uni, role="student")
    assert auth_client(other_user).get(url).status_code == 404
    # Verified -> visible, and the institution feed shows it.
    InstitutionMembership.objects.filter(pk=membership.pk).update(status="verified")
    assert auth_client(other_user).get(url).status_code == 200
    feed = auth_client(other_user).get(f"{SOCIAL}/audiences/institution/{uni.pk}/posts/").json()["results"]
    assert [p["body"] for p in feed] == ["EXU only"]
    # Revocation removes access immediately.
    InstitutionMembership.objects.filter(pk=membership.pk).update(status="revoked")
    assert auth_client(other_user).get(url).status_code == 404


def test_non_members_cannot_post_to_an_institution(auth_client, user, uni):
    response = auth_client(user).post(
        f"{SOCIAL}/posts/", {"body": "x", "visibility": "institution", "audience_id": str(uni.pk)}, format="json"
    )
    assert response.status_code == 403


def test_campus_audience(auth_client, user, other_user, uni):
    main = Campus.objects.create(institution=uni, name="Main", slug="main")
    annex = Campus.objects.create(institution=uni, name="Annex", slug="annex")
    verify(user, uni, campus=main)
    verify(other_user, uni, campus=annex)
    post = (
        auth_client(user)
        .post(
            f"{SOCIAL}/posts/",
            {"body": "Main campus", "visibility": "campus", "audience_id": str(main.pk)},
            format="json",
        )
        .json()
    )
    assert auth_client(other_user).get(f"{SOCIAL}/posts/{post['id']}/").status_code == 404


def test_institution_moderators_moderate_institution_posts(auth_client, user, other_user, uni):
    from university.permissions.models import Role

    verify(user, uni)
    post = (
        auth_client(user)
        .post(f"{SOCIAL}/posts/", {"body": "x", "visibility": "institution", "audience_id": str(uni.pk)}, format="json")
        .json()
    )
    Role.objects.create(
        key="exu_mod", name="EXU moderator", scope_type="institution", permissions=["social.content.moderate"]
    )
    assign_role(user=other_user, role_key="exu_mod", scope=Scope("institution", uni.pk))
    assert (
        auth_client(other_user)
        .post(f"{SOCIAL}/posts/{post['id']}/hide/", {"reason": "off-topic"}, format="json")
        .status_code
        == 204
    )


def test_profile_combines_module_extras(api_client, auth_client, user, uni):
    verify(user, uni)
    auth_client(user).patch(f"{SOCIAL}/me/profile/", {"bio": "Engineer"}, format="json")
    extras = api_client.get(f"/api/v1/users/{user.pk}/").json()["extras"]
    assert extras["institutions"][0]["short_name"] == "EXU"
    assert extras["social"]["bio"] == "Engineer"


def test_export_and_purge_span_modules(auth_client, user, uni):
    from university.core.testing import PASSWORD
    from university.social.models import Post
    from university.users.services import delete_account, purge_user

    verify(user, uni)
    auth_client(user).post(f"{SOCIAL}/posts/", {"body": "hello"}, format="json")
    data = auth_client(user).get("/api/v1/me/export/").json()
    assert data["institution_memberships"] and data["social"]["posts"]
    delete_account(user, password=PASSWORD)
    purge_user(type(user).all_objects.get(pk=user.pk))
    assert not Post.all_objects.filter(author=user).exists()


def test_openapi_schema_valid_for_whole_platform(tmp_path):
    call_command("spectacular", "--validate", "--fail-on-warn", "--file", str(tmp_path / "schema.yml"))
    assert (tmp_path / "schema.yml").stat().st_size > 10_000


def test_other_user_fixture_is_isolated():
    assert create_user("iso@example.com", handle="iso").pk
