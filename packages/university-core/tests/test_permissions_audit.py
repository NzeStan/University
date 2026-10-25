"""Scoped RBAC and audit logging."""

from __future__ import annotations

import pytest

from tests.testapp.state import CLUB_PARENTS
from university.audit.models import AuditLog, AuditLogImmutableError
from university.audit.services import record, verify_entries
from university.core.exceptions import Conflict, PermissionDenied, ValidationError
from university.core.testing import create_user
from university.permissions.models import Role, RoleAssignment
from university.permissions.scopes import Scope
from university.permissions.services import (
    assign_role,
    authorize,
    get_effective_permissions,
    has_permission,
    revoke_role,
)

pytestmark = pytest.mark.django_db


# ------------------------------------------------------------- permissions
def test_system_roles_are_synced():
    assert Role.objects.filter(key="platform_admin", is_system=True).exists()
    assert Role.objects.filter(key="school_editor", scope_type="school").exists()


def test_platform_role_applies_everywhere(user):
    assert not has_permission(user, "testapp.widgets.view")
    assign_role(user=user, role_key="widget_viewer")
    assert has_permission(user, "testapp.widgets.view")
    assert has_permission(user, "testapp.widgets.view", Scope("school", "s1"))
    assert not has_permission(user, "testapp.widgets.edit")


def test_scoped_role_is_confined_to_its_scope(user):
    assign_role(user=user, role_key="school_editor", scope=Scope("school", "s1"))
    assert has_permission(user, "testapp.widgets.edit", Scope("school", "s1"))
    assert not has_permission(user, "testapp.widgets.edit", Scope("school", "s2"))
    assert not has_permission(user, "testapp.widgets.edit")  # not platform-wide


def test_parent_scope_grants_flow_to_children(user):
    CLUB_PARENTS["c1"] = "s1"
    assign_role(user=user, role_key="school_editor", scope=Scope("school", "s1"))
    assert has_permission(user, "testapp.widgets.edit", Scope("club", "c1"))
    assert not has_permission(user, "testapp.widgets.edit", Scope("club", "c2"))


def test_permission_changes_take_effect_immediately(user):
    assignment = assign_role(user=user, role_key="widget_viewer")
    assert has_permission(user, "testapp.widgets.view")
    revoke_role(assignment)
    fresh = type(user).objects.get(pk=user.pk)
    assert not has_permission(fresh, "testapp.widgets.view")
    # Role edits invalidate caches too.
    assign_role(user=user, role_key="club_viewer", scope=Scope("club", "c9"))
    assert has_permission(type(user).objects.get(pk=user.pk), "testapp.widgets.view", Scope("club", "c9"))
    Role.objects.filter(key="club_viewer").update(permissions=[])
    role = Role.objects.get(key="club_viewer")
    role.save()
    assert not has_permission(type(user).objects.get(pk=user.pk), "testapp.widgets.view", Scope("club", "c9"))


def test_expired_assignment_ignored(user):
    import datetime as dt

    from django.utils import timezone

    assign_role(user=user, role_key="widget_viewer", expires_at=timezone.now() - dt.timedelta(seconds=1))
    assert not has_permission(user, "testapp.widgets.view")


def test_duplicate_assignment_conflict(user):
    assign_role(user=user, role_key="widget_viewer")
    with pytest.raises(Conflict):
        assign_role(user=user, role_key="widget_viewer")


def test_role_scope_mismatch_and_unknown_scope(user):
    with pytest.raises(ValidationError):
        assign_role(user=user, role_key="school_editor")  # school role at platform scope
    with pytest.raises(ValidationError):
        assign_role(user=user, role_key="school_editor", scope=Scope("galaxy", "x"))


@pytest.mark.security
def test_no_privilege_escalation_through_role_assignment(user, other_user):
    # A school editor who may assign roles in their school cannot hand out the
    # platform admin role, nor roles outside their school.
    custom = Role.objects.create(
        key="school_lead",
        name="School lead",
        scope_type="school",
        permissions=["testapp.widgets.*", "permissions.roles.assign", "permissions.roles.view"],
    )
    assign_role(user=user, role_key=custom.key, scope=Scope("school", "s1"))
    assign_role(user=other_user, role_key="school_editor", scope=Scope("school", "s1"), granted_by=user)
    with pytest.raises(PermissionDenied):
        assign_role(user=other_user, role_key="platform_admin", granted_by=user)
    with pytest.raises(PermissionDenied):
        assign_role(user=other_user, role_key="school_editor", scope=Scope("school", "s2"), granted_by=user)
    powerful = Role.objects.create(key="school_super", name="x", scope_type="school", permissions=["testapp.secret"])
    with pytest.raises(PermissionDenied):
        assign_role(user=other_user, role_key=powerful.key, scope=Scope("school", "s1"), granted_by=user)


def test_inactive_users_hold_nothing(superuser):
    assert has_permission(superuser, "anything.at.all")
    superuser.status = "suspended"
    superuser.save()
    assert not has_permission(superuser, "anything.at.all")


def test_authorize_raises_and_audits(user):
    with pytest.raises(PermissionDenied):
        authorize(user, "testapp.secret", audit_denial=True)
    assert AuditLog.objects.filter(action="permission.denied", outcome="denied").exists()


def test_effective_permissions_endpoint(auth_client, user):
    assign_role(user=user, role_key="school_editor", scope=Scope("school", "s1"))
    data = auth_client(user).get("/api/v1/me/permissions/?scope_type=school&scope_id=s1").json()
    assert {"testapp.widgets.view", "testapp.widgets.edit"} <= set(data["permissions"])
    assert get_effective_permissions(user) == []


def test_role_assignment_api_enforces_scope(auth_client, user, other_user, superuser):
    payload = {"user": str(other_user.pk), "role": "school_editor", "scope_type": "school", "scope_id": "s1"}
    assert auth_client(user).post("/api/v1/role-assignments/", payload, format="json").status_code == 403
    created = auth_client(superuser).post("/api/v1/role-assignments/", payload, format="json")
    assert created.status_code == 201
    assert auth_client(user).get("/api/v1/role-assignments/?scope_type=school&scope_id=s1").status_code == 403
    listed = auth_client(superuser).get("/api/v1/role-assignments/?scope_type=school&scope_id=s1").json()
    assert listed[0]["role"] == "school_editor"
    assert auth_client(user).delete(f"/api/v1/role-assignments/{created.json()['id']}/").status_code == 403
    assert auth_client(superuser).delete(f"/api/v1/role-assignments/{created.json()['id']}/").status_code == 204
    assert RoleAssignment.objects.get(pk=created.json()["id"]).revoked_at is not None


def test_system_roles_cannot_be_edited_via_api(auth_client, superuser):
    role = Role.objects.get(key="platform_admin")
    response = auth_client(superuser).patch(f"/api/v1/roles/{role.pk}/", {"permissions": []}, format="json")
    assert response.status_code == 403
    custom = auth_client(superuser).post(
        "/api/v1/roles/",
        {"key": "helpers", "name": "Helpers", "scope_type": "platform", "permissions": ["testapp.widgets.view"]},
        format="json",
    )
    assert custom.status_code == 201 and custom.json()["is_system"] is False
    bad = auth_client(superuser).post(
        "/api/v1/roles/",
        {"key": "bad", "name": "Bad", "scope_type": "platform", "permissions": ["no.such.perm"]},
        format="json",
    )
    assert bad.status_code == 400


def test_widget_view_permission_class(auth_client, user):
    assert auth_client(user).get("/api/v1/testapp/widgets/").status_code == 403
    assign_role(user=user, role_key="widget_viewer")
    assert auth_client(user).get("/api/v1/testapp/widgets/").status_code == 200


# ------------------------------------------------------------------ audit
def test_audit_entries_are_append_only(user):
    entry = record("unit.test.action", actor=user, metadata={"password": "secret", "note": "ok"})
    assert entry.metadata == {"password": "[REDACTED]", "note": "ok"}
    entry.action = "tampered"
    with pytest.raises(AuditLogImmutableError):
        entry.save()
    with pytest.raises(AuditLogImmutableError):
        entry.delete()
    with pytest.raises(AuditLogImmutableError):
        AuditLog.objects.filter(pk=entry.pk).update(action="x")
    with pytest.raises(AuditLogImmutableError):
        AuditLog.objects.all().delete()


@pytest.mark.security
def test_audit_tampering_is_detected(user):
    record("unit.one", actor=user)
    entry = record("unit.two", actor=user)
    assert list(verify_entries()) == []
    # Simulate a direct database modification bypassing the ORM guards.
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {AuditLog._meta.db_table} SET action = %s WHERE id = %s", ["unit.forged", entry.pk.hex])
    issues = list(verify_entries())
    assert [i.problem for i in issues] == ["hash_mismatch"]


def test_hash_chain(user, settings):
    settings.UNIVERSITY = {**settings.UNIVERSITY, "AUDIT": {"HASH_CHAIN": True}}
    a = record("chain.one", actor=user)
    b = record("chain.two", actor=user)
    assert b.previous_hash == a.entry_hash
    assert list(verify_entries(check_chain=True)) == []


def test_audit_log_api_requires_permission(auth_client, user, superuser):
    record("unit.visible", actor=user)
    assert auth_client(user).get("/api/v1/audit/logs/").status_code == 403
    response = auth_client(superuser).get("/api/v1/audit/logs/?action=unit.visible")
    assert response.status_code == 200 and response.json()["results"][0]["action"] == "unit.visible"
    assert auth_client(superuser).get("/api/v1/audit/logs/?actor=not-a-uuid").status_code == 400
    # Unknown filters are ignored rather than passed to the ORM.
    assert auth_client(superuser).get("/api/v1/audit/logs/?actor__password__startswith=a").status_code == 200


def test_my_activity_only_shows_own_events(auth_client, user, other_user):
    record("auth.custom.thing", actor=user)
    record("auth.custom.other", actor=other_user)
    actions = [e["action"] for e in auth_client(user).get("/api/v1/me/activity/").json()["results"]]
    assert "auth.custom.thing" in actions and "auth.custom.other" not in actions


def test_audit_can_be_disabled(settings, user):
    settings.UNIVERSITY = {**settings.UNIVERSITY, "AUDIT": {"ENABLED": False}}
    assert record("unit.off", actor=user) is None


def test_management_commands(user, capsys):
    from django.core.management import call_command

    call_command("university_modules", "--permissions")
    out = capsys.readouterr().out
    assert "testapp" in out and "audit.view" in out
    call_command("university_purge", "--dry-run")
    call_command("university_verify_audit")
    assert "no issues" in capsys.readouterr().out


def test_create_user_unique_constraint_on_verified_phone():
    from django.db import IntegrityError, transaction
    from django.utils import timezone

    create_user("p1@example.com", phone_number="+2348011111111", phone_verified_at=timezone.now())
    create_user("p2@example.com", phone_number="+2348011111111")  # unverified claim allowed
    with pytest.raises(IntegrityError), transaction.atomic():
        create_user("p3@example.com", phone_number="+2348011111111", phone_verified_at=timezone.now())
