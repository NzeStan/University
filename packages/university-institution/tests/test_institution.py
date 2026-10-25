"""university-institution: structure, memberships, verification, security boundaries."""

from __future__ import annotations

import datetime as dt
import json
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from university.audit.models import AuditLog
from university.core.events import event_bus
from university.core.testing import create_user
from university.institution import services
from university.institution.constants import MembershipStatus
from university.institution.models import (
    AcademicSession,
    AcademicUnit,
    Campus,
    Faculty,
    Institution,
    InstitutionDomain,
    InstitutionMembership,
    InstitutionType,
    VerificationRequest,
)
from university.permissions.scopes import Scope
from university.permissions.services import assign_role, has_permission

pytestmark = pytest.mark.django_db
BASE = "/api/v1"
PDF = b"%PDF-1.4\n" + b"0" * 200


@pytest.fixture
def uni(db):
    inst = Institution.objects.create(
        name="Example University",
        short_name="EXU",
        slug="exu",
        country="NG",
        type=InstitutionType.objects.get(key="university"),
    )
    InstitutionDomain.objects.create(institution=inst, domain="exu.edu.ng", is_verified=True, allow_subdomains=True)
    return inst


@pytest.fixture
def poly(db):
    return Institution.objects.create(
        name="Sample Polytechnic",
        short_name="SPT",
        slug="spt",
        country="GH",
        type=InstitutionType.objects.get(key="polytechnic"),
    )


@pytest.fixture
def uni_admin(uni):
    admin = create_user("admin@exu.edu.ng", handle="exuadmin")
    assign_role(user=admin, role_key="institution_admin", scope=Scope("institution", uni.pk))
    return admin


def _code(outbox) -> str:
    return re.search(r"\b(\d{6})\b", outbox[-1].body).group(1)


# ------------------------------------------------------------ institutions
def test_institution_types_are_seeded_from_settings(api_client):
    keys = {t["key"] for t in api_client.get(f"{BASE}/institution-types/").json()}
    assert {"university", "polytechnic", "college_of_education", "monotechnic"} <= keys


def test_public_listing_and_filters(api_client, uni, poly):
    data = api_client.get(f"{BASE}/institutions/").json()
    assert data["count"] == 2
    assert [i["slug"] for i in api_client.get(f"{BASE}/institutions/?country=gh").json()["results"]] == ["spt"]
    assert [i["slug"] for i in api_client.get(f"{BASE}/institutions/?type=university").json()["results"]] == ["exu"]
    assert api_client.get(f"{BASE}/institutions/?q=polytech").json()["count"] == 1
    detail = api_client.get(f"{BASE}/institutions/{uni.pk}/").json()
    assert detail["available_verification_methods"] == ["institution_email", "manual"]


def test_inactive_institutions_are_hidden(api_client, uni, uni_admin, auth_client):
    uni.status = "inactive"
    uni.save()
    assert api_client.get(f"{BASE}/institutions/{uni.pk}/").status_code == 404
    assert auth_client(uni_admin).get(f"{BASE}/institutions/{uni.pk}/").status_code == 200


def test_create_requires_platform_permission(auth_client, user, superuser):
    payload = {"name": "New College", "short_name": "NC", "type": "college_of_education", "country": "ke"}
    assert auth_client(user).post(f"{BASE}/institutions/", payload, format="json").status_code == 403
    created = auth_client(superuser).post(f"{BASE}/institutions/", payload, format="json")
    assert created.status_code == 201
    assert created.json()["country"] == "KE" and created.json()["slug"] == "nc"
    dup = auth_client(superuser).post(f"{BASE}/institutions/", payload, format="json")
    assert dup.status_code == 409


@pytest.mark.security
def test_institution_admin_scope_is_enforced(auth_client, uni, poly, uni_admin):
    client = auth_client(uni_admin)
    assert client.patch(f"{BASE}/institutions/{uni.pk}/", {"city": "Lagos"}, format="json").status_code == 200
    # BOLA: cannot edit another institution.
    assert client.patch(f"{BASE}/institutions/{poly.pk}/", {"city": "Accra"}, format="json").status_code == 403
    # Privilege escalation: cannot self-verify or change status.
    assert client.patch(f"{BASE}/institutions/{uni.pk}/", {"is_verified": True}, format="json").status_code == 403
    uni.refresh_from_db()
    assert uni.city == "Lagos" and not uni.is_verified


def test_unknown_verification_methods_rejected(auth_client, uni, uni_admin):
    response = auth_client(uni_admin).patch(
        f"{BASE}/institutions/{uni.pk}/", {"verification_methods": ["telepathy"]}, format="json"
    )
    assert response.status_code == 400


# ------------------------------------------------------------ domains
def test_domain_management(api_client, auth_client, uni, uni_admin, superuser):
    added = auth_client(uni_admin).post(
        f"{BASE}/institutions/{uni.pk}/domains/", {"domain": "Alumni.EXU.edu.ng"}, format="json"
    )
    assert added.status_code == 201
    assert added.json() == {**added.json(), "domain": "alumni.exu.edu.ng", "is_verified": False}
    # Unverified domains are not publicly listed and cannot verify members.
    public = [d["domain"] for d in api_client.get(f"{BASE}/institutions/{uni.pk}/domains/").json()]
    assert public == ["exu.edu.ng"]
    by_platform = auth_client(superuser).post(
        f"{BASE}/institutions/{uni.pk}/domains/", {"domain": "exu.ac.ng"}, format="json"
    )
    assert by_platform.json()["is_verified"] is True
    assert (
        auth_client(uni_admin)
        .post(f"{BASE}/institutions/{uni.pk}/domains/", {"domain": "exu.ac.ng"}, format="json")
        .status_code
        == 409
    )
    assert (
        auth_client(uni_admin)
        .post(f"{BASE}/institutions/{uni.pk}/domains/", {"domain": "not a domain"}, format="json")
        .status_code
        == 400
    )


# ------------------------------------------------------------ structure
def test_structure_crud_and_tree(auth_client, api_client, uni, uni_admin):
    client = auth_client(uni_admin)
    faculty = client.post(
        f"{BASE}/institutions/{uni.pk}/units/", {"unit_type": "faculty", "name": "Faculty of Science"}, format="json"
    )
    assert faculty.status_code == 201
    dept = client.post(
        f"{BASE}/institutions/{uni.pk}/units/",
        {"unit_type": "department", "name": "Computer Science", "parent": faculty.json()["id"]},
        format="json",
    ).json()
    roots = api_client.get(f"{BASE}/institutions/{uni.pk}/units/?parent=root").json()
    assert [u["name"] for u in roots] == ["Faculty of Science"]
    assert Faculty.objects.count() == 1
    programme = client.post(
        f"{BASE}/institutions/{uni.pk}/programmes/",
        {
            "name": "B.Sc. Computer Science",
            "code": "CSC",
            "award": "B.Sc.",
            "qualification_level": "bachelor",
            "academic_unit": dept["id"],
        },
        format="json",
    )
    assert programme.status_code == 201, programme.json()
    level = client.post(
        f"{BASE}/institutions/{uni.pk}/levels/", {"code": "100", "name": "100 Level", "order": 1}, format="json"
    )
    assert level.status_code == 201
    bad = client.post(f"{BASE}/institutions/{uni.pk}/units/", {"unit_type": "planet", "name": "X"}, format="json")
    assert bad.status_code == 400
    # Cycle prevention: a faculty cannot move under its own department.
    cycle = client.patch(
        f"{BASE}/institutions/{uni.pk}/units/{faculty.json()['id']}/", {"parent": dept["id"]}, format="json"
    )
    assert cycle.status_code == 400


@pytest.mark.security
def test_cross_institution_references_are_rejected(auth_client, uni, poly, superuser, uni_admin):
    foreign_unit = AcademicUnit.objects.create(institution=poly, unit_type="faculty", name="Engineering", slug="eng")
    response = auth_client(uni_admin).post(
        f"{BASE}/institutions/{uni.pk}/units/",
        {"unit_type": "department", "name": "Mech", "parent": str(foreign_unit.pk)},
        format="json",
    )
    assert response.status_code == 400
    assert (
        auth_client(uni_admin)
        .post(f"{BASE}/institutions/{poly.pk}/campuses/", {"name": "Hijack"}, format="json")
        .status_code
        == 403
    )
    # Detail lookups are confined to the institution in the URL.
    assert auth_client(superuser).get(f"{BASE}/institutions/{uni.pk}/units/{foreign_unit.pk}/").status_code == 404


def test_campus_main_and_sessions(auth_client, uni, uni_admin):
    client = auth_client(uni_admin)
    client.post(f"{BASE}/institutions/{uni.pk}/campuses/", {"name": "Main", "is_main": True}, format="json")
    client.post(f"{BASE}/institutions/{uni.pk}/campuses/", {"name": "Annex", "is_main": True}, format="json")
    assert list(Campus.objects.filter(is_main=True).values_list("name", flat=True)) == ["Annex"]
    first = client.post(
        f"{BASE}/institutions/{uni.pk}/sessions/",
        {"name": "2025/2026", "starts_on": "2025-09-01", "ends_on": "2026-08-31", "make_current": True},
        format="json",
    ).json()
    second = client.post(
        f"{BASE}/institutions/{uni.pk}/sessions/",
        {"name": "2026/2027", "starts_on": "2026-09-01", "ends_on": "2027-08-31", "make_current": True},
        format="json",
    ).json()
    assert list(AcademicSession.objects.filter(is_current=True).values_list("pk", flat=True)) == [
        __import__("uuid").UUID(second["id"])
    ]
    semester = client.post(
        f"{BASE}/institutions/{uni.pk}/sessions/{first['id']}/semesters/",
        {"name": "Harmattan", "order": 1},
        format="json",
    )
    assert semester.status_code == 201
    bad_dates = client.post(
        f"{BASE}/institutions/{uni.pk}/sessions/",
        {"name": "x", "starts_on": "2026-01-01", "ends_on": "2025-01-01"},
        format="json",
    )
    assert bad_dates.status_code == 400


def test_campus_scope_inherits_institution_grants(uni, uni_admin):
    campus = Campus.objects.create(institution=uni, name="Main", slug="main")
    assert has_permission(uni_admin, "institution.structure.manage", Scope("campus", campus.pk))


# ------------------------------------------------------------ memberships
def _join(client, institution, role="student", **extra):
    return client.post(
        f"{BASE}/me/memberships/", {"institution": str(institution.pk), "role": role, **extra}, format="json"
    )


def test_join_and_duplicate(auth_client, user, uni):
    client = auth_client(user)
    joined = _join(client, uni)
    assert joined.status_code == 201
    body = joined.json()
    assert body["status"] == "pending" and body["is_primary"] is True
    assert _join(client, uni).status_code == 409
    assert _join(client, uni, role="wizard").status_code == 400
    assert len(client.get(f"{BASE}/me/memberships/").json()) == 1


@pytest.mark.security
def test_join_rejects_foreign_structure(auth_client, user, uni, poly):
    campus = Campus.objects.create(institution=poly, name="Accra", slug="accra")
    assert _join(auth_client(user), uni, campus=str(campus.pk)).status_code == 400


def test_guest_role_auto_verifies_and_emits_events(auth_client, user, uni):
    seen = []
    event_bus.subscribe("institution.*", seen.append)
    try:
        assert _join(auth_client(user), uni, role="guest").json()["status"] == "verified"
    finally:
        event_bus.unsubscribe("institution.*", seen.append)
    assert {"institution.membership.requested", "institution.membership.verified", "institution.joined"} <= {
        e.name for e in seen
    }
    assert all("user_id" in e.payload for e in seen)


def test_single_institution_policy_and_limits(auth_client, user, uni, poly):
    client = auth_client(user)
    with override_settings(UNIVERSITY={"INSTITUTION": {"ALLOW_MULTIPLE_INSTITUTIONS": False}}):
        _join(client, uni)
        assert _join(client, poly).status_code == 400
    with override_settings(UNIVERSITY={"INSTITUTION": {"MAX_ACTIVE_MEMBERSHIPS_PER_USER": 1}}):
        assert _join(client, uni, role="alumni").json()["error"]["code"] == "membership_limit"


def test_institution_email_verification(auth_client, user, other_user, uni, outbox):
    client = auth_client(user)
    membership = _join(client, uni).json()
    url = f"{BASE}/me/memberships/{membership['id']}/verifications/"
    wrong_domain = client.post(url, {"method": "institution_email", "email": "ada@gmail.com"}, format="json")
    assert wrong_domain.status_code == 400 and wrong_domain.json()["error"]["code"] == "domain_not_allowed"
    started = client.post(url, {"method": "institution_email", "email": "ada@student.exu.edu.ng"}, format="json")
    assert started.status_code == 201
    started = started.json()
    assert started["status"] == "awaiting_user" and started["evidence"] == {"email": "a***a@student.exu.edu.ng"}
    complete = f"{url}{started['id']}/complete/"
    assert (
        client.post(complete, {"code": "000000" if _code(outbox) != "000000" else "111111"}, format="json").status_code
        == 400
    )
    done = client.post(complete, {"code": _code(outbox)}, format="json")
    assert done.status_code == 200 and done.json()["status"] == "approved"
    assert InstitutionMembership.objects.get(pk=membership["id"]).status == MembershipStatus.VERIFIED

    # The same institutional address cannot verify a second account.
    other = auth_client(other_user)
    other_membership = _join(other, uni).json()
    reused = other.post(
        f"{BASE}/me/memberships/{other_membership['id']}/verifications/",
        {"method": "institution_email", "email": "ada@student.exu.edu.ng"},
        format="json",
    )
    assert reused.status_code == 400 and reused.json()["error"]["code"] == "email_unavailable"


def test_method_must_be_offered_by_institution(auth_client, user, uni):
    membership = _join(auth_client(user), uni).json()
    response = auth_client(user).post(
        f"{BASE}/me/memberships/{membership['id']}/verifications/",
        {"method": "student_id", "identifier": "EXU/2021/001"},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.security
def test_identifier_review_flow_and_reviewer_boundaries(auth_client, user, other_user, uni, poly, uni_admin):
    uni.verification_methods = ["student_id", "manual"]
    uni.save()
    client = auth_client(user)
    membership = _join(client, uni).json()
    started = client.post(
        f"{BASE}/me/memberships/{membership['id']}/verifications/",
        {"method": "student_id", "identifier": "EXU/2021/0042"},
        format="json",
    )
    assert started.status_code == 201 and started.json()["status"] == "pending_review"
    stored = InstitutionMembership.objects.get(pk=membership["id"])
    assert "0042" not in stored.identifier_hash and stored.identifier_hint.endswith("042")

    # Someone else cannot claim the same student number.
    other = auth_client(other_user)
    other_membership = _join(other, uni).json()
    clash = other.post(
        f"{BASE}/me/memberships/{other_membership['id']}/verifications/",
        {"method": "student_id", "identifier": "exu/2021/0042"},
        format="json",
    )
    assert clash.status_code == 400

    approve_url = f"{BASE}/institutions/{uni.pk}/memberships/{membership['id']}/approve/"
    assert auth_client(other_user).post(approve_url, format="json").status_code == 403
    poly_admin = create_user("admin@spt.edu.gh", handle="sptadmin")
    assign_role(user=poly_admin, role_key="institution_admin", scope=Scope("institution", poly.pk))
    assert auth_client(poly_admin).post(approve_url, format="json").status_code == 403
    # Admins of another institution cannot even address it via their own URL.
    assert (
        auth_client(poly_admin)
        .post(f"{BASE}/institutions/{poly.pk}/memberships/{membership['id']}/approve/", format="json")
        .status_code
        == 404
    )

    members = auth_client(uni_admin).get(f"{BASE}/institutions/{uni.pk}/memberships/?status=pending").json()["results"]
    assert {m["id"] for m in members} == {membership["id"], other_membership["id"]}
    assert all("email" not in m["user"] for m in members)
    assert members[0]["pending_verification"] is not None or members[1]["pending_verification"] is not None

    approved = auth_client(uni_admin).post(approve_url, {"reason": "Checked roster"}, format="json")
    assert approved.status_code == 200 and approved.json()["status"] == "verified"
    assert VerificationRequest.objects.get(pk=started.json()["id"]).status == "approved"
    assert AuditLog.objects.filter(action="institution.membership.verified", actor=uni_admin).exists()


def test_reviewers_cannot_review_themselves(auth_client, uni, uni_admin):
    membership = _join(auth_client(uni_admin), uni, role="staff").json()
    response = auth_client(uni_admin).post(
        f"{BASE}/institutions/{uni.pk}/memberships/{membership['id']}/approve/", format="json"
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "self_review"


def test_member_list_requires_permission(auth_client, user, uni):
    assert auth_client(user).get(f"{BASE}/institutions/{uni.pk}/memberships/").status_code == 403


def test_document_verification_and_audited_download(auth_client, user, uni, uni_admin):
    uni.verification_methods = ["document"]
    uni.save()
    client = auth_client(user)
    membership = _join(client, uni).json()
    url = f"{BASE}/me/memberships/{membership['id']}/verifications/"
    evil = client.post(
        url, {"method": "document", "document": SimpleUploadedFile("id.pdf", b"MZ" + b"\x00" * 50)}, format="multipart"
    )
    assert evil.status_code == 400
    ok = client.post(url, {"method": "document", "document": SimpleUploadedFile("id.pdf", PDF)}, format="multipart")
    assert ok.status_code == 201 and ok.json()["has_document"] is True
    request = VerificationRequest.objects.get(pk=ok.json()["id"])
    assert request.document.name.startswith("institution/verification/") and request.document.name.endswith(".pdf")
    doc_url = f"{BASE}/institutions/{uni.pk}/memberships/{membership['id']}/verifications/{request.pk}/document/"
    assert client.get(doc_url).status_code == 403  # the applicant is not a reviewer
    download = auth_client(uni_admin).get(doc_url)
    assert download.status_code == 200 and b"".join(download.streaming_content) == PDF
    assert AuditLog.objects.filter(action="institution.verification.document_viewed").exists()


def test_reject_suspend_revoke_leave(auth_client, user, uni, uni_admin):
    client = auth_client(user)
    m1 = _join(client, uni).json()
    admin = auth_client(uni_admin)
    assert (
        admin.post(
            f"{BASE}/institutions/{uni.pk}/memberships/{m1['id']}/reject/", {"reason": "Not found"}, format="json"
        ).json()["status"]
        == "rejected"
    )
    assert (
        admin.post(
            f"{BASE}/institutions/{uni.pk}/memberships/{m1['id']}/reject/", {"reason": "x"}, format="json"
        ).status_code
        == 409
    )
    m2 = _join(client, uni).json()  # can re-apply after rejection
    admin.post(f"{BASE}/institutions/{uni.pk}/memberships/{m2['id']}/approve/", format="json")
    assert (
        admin.post(f"{BASE}/institutions/{uni.pk}/memberships/{m2['id']}/suspend/", {}, format="json").status_code
        == 400
    )
    assert (
        admin.post(
            f"{BASE}/institutions/{uni.pk}/memberships/{m2['id']}/suspend/", {"reason": "Policy"}, format="json"
        ).json()["status"]
        == "suspended"
    )
    assert (
        admin.post(
            f"{BASE}/institutions/{uni.pk}/memberships/{m2['id']}/revoke/", {"reason": "Expelled"}, format="json"
        ).json()["status"]
        == "revoked"
    )
    m3 = _join(client, uni, role="alumni").json()
    assert client.delete(f"{BASE}/me/memberships/{m3['id']}/").status_code == 204
    assert InstitutionMembership.objects.get(pk=m3["id"]).status == "left"


@pytest.mark.security
def test_users_cannot_touch_other_users_memberships(auth_client, user, other_user, uni):
    membership = _join(auth_client(other_user), uni).json()
    client = auth_client(user)
    assert client.get(f"{BASE}/me/memberships/{membership['id']}/").status_code == 404
    assert client.delete(f"{BASE}/me/memberships/{membership['id']}/").status_code == 404
    assert (
        client.patch(f"{BASE}/me/memberships/{membership['id']}/", {"entry_year": 2020}, format="json").status_code
        == 404
    )
    assert (
        client.post(
            f"{BASE}/me/memberships/{membership['id']}/verifications/", {"method": "manual"}, format="json"
        ).status_code
        == 404
    )


def test_membership_detail_updates_and_primary(auth_client, user, uni, poly):
    client = auth_client(user)
    m1 = _join(client, uni).json()
    m2 = _join(client, poly).json()
    assert client.post(f"{BASE}/me/memberships/{m2['id']}/primary/").json()["is_primary"] is True
    assert InstitutionMembership.objects.get(pk=m1["id"]).is_primary is False
    level = services.create_level  # noqa: F841 - structure created below via ORM for brevity
    response = client.patch(
        f"{BASE}/me/memberships/{m1['id']}/", {"entry_year": 2022, "graduation_year": 2020}, format="json"
    )
    assert response.status_code == 400
    response = client.patch(
        f"{BASE}/me/memberships/{m1['id']}/", {"entry_year": 2022, "graduation_year": 2026}, format="json"
    )
    assert response.json()["graduation_year"] == 2026


# ------------------------------------------------------------ privacy & integration
def test_profile_affiliations_respect_privacy(api_client, auth_client, user, uni):
    _join(auth_client(user), uni, role="guest")
    profile = api_client.get(f"{BASE}/users/{user.pk}/").json()
    assert profile["extras"]["institutions"][0]["short_name"] == "EXU"
    from university.users.services import get_privacy_settings, update_settings

    update_settings(get_privacy_settings(user), {"show_affiliations": False})
    assert "institutions" not in api_client.get(f"{BASE}/users/{user.pk}/").json()["extras"]


def test_data_export_includes_memberships(auth_client, user, uni):
    _join(auth_client(user), uni)
    data = auth_client(user).get(f"{BASE}/me/export/").json()
    assert data["institution_memberships"][0]["institution"] == "Example University"


def test_purge_clears_member_identifiers(user, uni):
    from university.core.testing import PASSWORD
    from university.users.services import delete_account, purge_user

    membership = services.request_membership(user=user, institution=uni, role="student")
    InstitutionMembership.objects.filter(pk=membership.pk).update(identifier_hash="x" * 64, identifier_hint="**042")
    delete_account(user, password=PASSWORD)
    purge_user(type(user).all_objects.get(pk=user.pk))
    assert InstitutionMembership.objects.get(pk=membership.pk).identifier_hash == ""


def test_import_command_is_idempotent(tmp_path, capsys):
    from django.core.management import call_command

    data = [
        {
            "name": "Coastal University",
            "short_name": "CU",
            "type": "university",
            "country": "ng",
            "domains": ["cu.edu.ng"],
            "campuses": [{"name": "Main", "is_main": True}],
        },
        {"name": "Broken", "type": "spaceport"},
    ]
    path = tmp_path / "institutions.json"
    path.write_text(json.dumps(data))
    call_command("university_import_institutions", str(path))
    call_command("university_import_institutions", str(path), "--verify-domains")
    out = capsys.readouterr()
    assert "unknown type 'spaceport'" in out.err
    inst = Institution.objects.get(slug="cu")
    assert inst.country == "NG" and inst.campuses.count() == 1
    assert InstitutionDomain.objects.get(domain="cu.edu.ng").is_verified


def test_document_retention_policy(user, uni):
    from django.core.files.base import ContentFile
    from django.utils import timezone

    from university.core.retention import run_retention

    membership = services.request_membership(user=user, institution=uni, role="student")
    request = VerificationRequest.objects.create(
        membership=membership, method="document", status="approved", decided_at=timezone.now() - dt.timedelta(days=200)
    )
    request.document.save("x.pdf", ContentFile(PDF))
    assert run_retention(only=["institution.verification_documents"]) == {"institution.verification_documents": 1}
    request.refresh_from_db()
    assert not request.document


def test_module_registered_with_core(api_client):
    modules = {m["name"] for m in api_client.get(f"{BASE}/meta/modules/").json()}
    assert "institution" in modules


def test_verified_members_belong_to_institution_and_campus_audiences(user, uni):
    from university.core.audiences import forget, is_member, member_scopes

    campus = Campus.objects.create(institution=uni, name="Main", slug="main")
    membership = services.request_membership(user=user, institution=uni, role="student", campus=campus)
    assert member_scopes(user) == frozenset()  # pending members are not in the audience
    forget(user)
    InstitutionMembership.objects.filter(pk=membership.pk).update(status=MembershipStatus.VERIFIED)
    assert is_member(user, "institution", uni.pk) and is_member(user, "campus", campus.pk)


# --------------------------------------------------------- content adapter
@pytest.mark.security
def test_institution_adapter_is_display_only(uni, uni_admin, user):
    from university.core.content import content_types, get_adapter, get_moderatable_adapter
    from university.core.exceptions import NotFound

    adapter = get_adapter("institution.institution")
    ref = adapter.resolve(uni.pk)
    assert ref.excerpt == "Example University" and ref.author_id is None and not ref.is_anonymous
    assert ref.scope == ("institution", str(uni.pk))
    assert adapter.resolve("not-a-uuid") is None
    # Registered for display, but never reportable or actionable.
    assert adapter.moderatable is False
    assert "institution.institution" in content_types()
    assert "institution.institution" not in content_types(moderatable=True)
    with pytest.raises(NotFound):
        get_moderatable_adapter("institution.institution")
    # Visibility follows the institution API: inactive ones only for their managers.
    assert adapter.can_view(user, uni.pk) and adapter.can_view(None, uni.pk)
    Institution.objects.filter(pk=uni.pk).update(status="inactive")
    assert not adapter.can_view(user, uni.pk) and not adapter.can_view(None, uni.pk)
    assert adapter.can_view(uni_admin, uni.pk)
