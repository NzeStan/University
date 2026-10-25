"""Accounts: registration, verification, password/email flows, profiles, privacy, lifecycle."""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from university.audit.models import AuditLog
from university.core.testing import PASSWORD, create_user
from university.users import services
from university.users.constants import UserStatus

pytestmark = pytest.mark.django_db
User = get_user_model()


def _token_from(mail_body: str, param: str = "token") -> str:
    match = re.search(rf"[?&]{param}=([^&\s]+)", mail_body)
    assert match, mail_body
    return match.group(1)


# ------------------------------------------------------------ registration
def test_verify_first_registration_flow(api_client, outbox):
    response = api_client.post(
        "/api/v1/auth/register/",
        {"email": "New@Example.com", "password": PASSWORD, "handle": "newbie", "consents": {"terms_of_service": True}},
        format="json",
    )
    assert response.status_code == 202
    user = User.objects.get(email="new@example.com")
    assert user.status == UserStatus.PENDING and not user.is_active
    assert user.consents.filter(purpose="terms_of_service", granted=True).exists()

    # Pending accounts cannot sign in, and the error is generic.
    login = api_client.post(
        "/api/v1/auth/login/", {"identifier": "new@example.com", "password": PASSWORD}, format="json"
    )
    assert login.status_code == 401 and login.json()["error"]["code"] == "invalid_credentials"

    token = _token_from(outbox[0].body)
    assert api_client.post("/api/v1/auth/email/verify/", {"token": token}, format="json").status_code == 200
    user.refresh_from_db()
    assert user.status == UserStatus.ACTIVE and user.email_verified
    login = api_client.post("/api/v1/auth/login/", {"identifier": "newbie", "password": PASSWORD}, format="json")
    assert login.status_code == 200 and "access" in login.json()


@pytest.mark.security
def test_registration_does_not_enumerate_accounts(api_client, user, outbox):
    new = api_client.post("/api/v1/auth/register/", {"email": "fresh@example.com", "password": PASSWORD}, format="json")
    dup = api_client.post("/api/v1/auth/register/", {"email": "ADA@example.com", "password": PASSWORD}, format="json")
    assert new.status_code == dup.status_code == 202
    assert new.json() == dup.json()
    # The real owner is told someone tried to use their address.
    assert any("already have one" in m.body for m in outbox if m.to == ["ada@example.com"])
    assert User.objects.filter(email="ada@example.com").count() == 1


def test_open_registration_returns_tokens(api_client):
    with override_settings(UNIVERSITY={"USERS": {"REGISTRATION_MODE": "open"}}):
        response = api_client.post(
            "/api/v1/auth/register/", {"email": "o@example.com", "password": PASSWORD}, format="json"
        )
        assert response.status_code == 201
        body = response.json()
        assert body["user"]["email"] == "o@example.com" and body["tokens"]["access"]
        dup = api_client.post("/api/v1/auth/register/", {"email": "o@example.com", "password": PASSWORD}, format="json")
        assert dup.status_code == 400


def test_registration_validates_password_and_handle(api_client, user):
    weak = api_client.post("/api/v1/auth/register/", {"email": "w@example.com", "password": "123"}, format="json")
    assert weak.status_code == 400 and "password" in weak.json()["error"]["details"]
    taken = api_client.post(
        "/api/v1/auth/register/", {"email": "h@example.com", "password": PASSWORD, "handle": "ADA"}, format="json"
    )
    assert taken.status_code == 400 and "handle" in taken.json()["error"]["details"]
    reserved = api_client.post(
        "/api/v1/auth/register/", {"email": "r@example.com", "password": PASSWORD, "handle": "admin"}, format="json"
    )
    assert reserved.status_code == 400


def test_registration_can_be_closed(api_client):
    with override_settings(UNIVERSITY={"USERS": {"ALLOW_REGISTRATION": False}}):
        response = api_client.post(
            "/api/v1/auth/register/", {"email": "c@example.com", "password": PASSWORD}, format="json"
        )
        assert response.status_code == 403 and response.json()["error"]["code"] == "registration_closed"


def test_verification_token_invalid_after_email_change(api_client, outbox):
    api_client.post("/api/v1/auth/register/", {"email": "t@example.com", "password": PASSWORD}, format="json")
    token = _token_from(outbox[0].body)
    User.objects.filter(email="t@example.com").update(email="changed@example.com")
    response = api_client.post("/api/v1/auth/email/verify/", {"token": token}, format="json")
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_token"
    assert api_client.post("/api/v1/auth/email/verify/", {"token": "garbage"}, format="json").status_code == 400


# ------------------------------------------------------------ passwords
@pytest.mark.security
def test_password_reset_flow_and_no_enumeration(api_client, user, outbox):
    tokens = api_client.post("/api/v1/auth/login/", {"identifier": "ada", "password": PASSWORD}, format="json").json()
    unknown = api_client.post("/api/v1/auth/password/reset/", {"email": "nobody@example.com"}, format="json")
    known = api_client.post("/api/v1/auth/password/reset/", {"email": "ada@example.com"}, format="json")
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    assert len([m for m in outbox if "reset" in m.subject.lower()]) == 1
    reset_mail = next(m for m in outbox if "reset" in m.subject.lower())
    uid, token = _token_from(reset_mail.body, "uid"), _token_from(reset_mail.body)

    new_password = "Another-Secure-Pass-42"
    response = api_client.post(
        "/api/v1/auth/password/reset/confirm/",
        {"uid": uid, "token": token, "new_password": new_password},
        format="json",
    )
    assert response.status_code == 200
    # Token is single use.
    again = api_client.post(
        "/api/v1/auth/password/reset/confirm/",
        {"uid": uid, "token": token, "new_password": "Yet-Another-Pass-77"},
        format="json",
    )
    assert again.status_code == 400
    # Existing sessions are invalidated.
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert api_client.get("/api/v1/me/").status_code == 401
    api_client.credentials()
    assert (
        api_client.post(
            "/api/v1/auth/login/", {"identifier": "ada", "password": new_password}, format="json"
        ).status_code
        == 200
    )


def test_password_change_keeps_current_session_only(api_client, user):
    first = api_client.post("/api/v1/auth/login/", {"identifier": "ada", "password": PASSWORD}, format="json").json()
    second = api_client.post("/api/v1/auth/login/", {"identifier": "ada", "password": PASSWORD}, format="json").json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {first['access']}")
    bad = api_client.post(
        "/api/v1/me/password/", {"current_password": "wrong", "new_password": "New-Password-123x"}, format="json"
    )
    assert bad.status_code == 400
    ok = api_client.post(
        "/api/v1/me/password/", {"current_password": PASSWORD, "new_password": "New-Password-123x"}, format="json"
    )
    assert ok.status_code == 200
    assert api_client.get("/api/v1/me/").status_code == 401  # old access token is dead
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {ok.json()['access']}")
    assert api_client.get("/api/v1/me/").status_code == 200  # current session survives
    refreshed = api_client.post("/api/v1/auth/token/refresh/", {"refresh": first["refresh"]}, format="json")
    assert refreshed.status_code == 200
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {second['access']}")
    assert api_client.get("/api/v1/me/").status_code == 401  # other session revoked
    assert AuditLog.objects.filter(action="account.password.changed").exists()


# ------------------------------------------------------------ email & phone
def test_email_change_requires_confirmation(auth_client, user, outbox):
    client = auth_client(user)
    response = client.post("/api/v1/me/email/", {"new_email": "ada2@example.com", "password": PASSWORD}, format="json")
    assert response.status_code == 202
    confirm = next(m for m in outbox if m.to == ["ada2@example.com"])
    assert any(m.to == ["ada@example.com"] for m in outbox)  # old address notified
    user.refresh_from_db()
    assert user.email == "ada@example.com" and user.pending_email == "ada2@example.com"
    assert (
        client.post(
            "/api/v1/auth/email/change/confirm/", {"token": _token_from(confirm.body)}, format="json"
        ).status_code
        == 200
    )
    user.refresh_from_db()
    assert user.email == "ada2@example.com" and user.pending_email == ""


@pytest.mark.security
def test_email_change_to_taken_address_is_silent(auth_client, user, other_user, outbox):
    response = auth_client(user).post(
        "/api/v1/me/email/", {"new_email": "grace@example.com", "password": PASSWORD}, format="json"
    )
    assert response.status_code == 202
    assert not any(m.to == ["grace@example.com"] for m in outbox)


def test_phone_verification(auth_client, user, settings):
    client = auth_client(user)
    sent: list[tuple[str, str]] = []

    class Capture:
        def send(self, to, body):
            sent.append((to, body))

    from university.core import providers

    providers.reset_provider_cache()
    settings.UNIVERSITY = {**settings.UNIVERSITY, "PROVIDERS": {"SMS": Capture}}
    try:
        start = client.post("/api/v1/me/phone/", {"phone_number": "+234 801 234 5678"}, format="json")
        assert start.status_code == 202
        code = re.search(r"\d{6}", sent[0][1]).group(0)
        assert sent[0][0] == "+2348012345678"
        wrong = client.post(
            "/api/v1/me/phone/verify/",
            {
                "phone_number": "+2348012345678",
                "challenge_id": start.json()["challenge_id"],
                "code": "000000" if code != "000000" else "111111",
            },
            format="json",
        )
        assert wrong.status_code == 400
        ok = client.post(
            "/api/v1/me/phone/verify/",
            {"phone_number": "+2348012345678", "challenge_id": start.json()["challenge_id"], "code": code},
            format="json",
        )
        assert ok.status_code == 200 and ok.json()["phone_verified"]
    finally:
        providers.reset_provider_cache()


# ------------------------------------------------------------ profile & privacy
@pytest.mark.security
def test_me_mass_assignment_is_ignored(auth_client, user):
    response = auth_client(user).patch(
        "/api/v1/me/",
        {
            "display_name": "Ada L.",
            "status": "banned",
            "is_staff": True,
            "email": "x@evil.com",
            "id": "00000000-0000-0000-0000-000000000000",
        },
        format="json",
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.display_name == "Ada L."
    assert user.status == UserStatus.ACTIVE and not user.is_staff and user.email == "ada@example.com"


def test_handle_change_conflict(auth_client, user, other_user):
    response = auth_client(user).patch("/api/v1/me/", {"handle": "grace"}, format="json")
    assert response.status_code == 400


def test_public_profile_respects_privacy(api_client, auth_client, user, other_user):
    assert api_client.get(f"/api/v1/users/{user.pk}/").status_code == 200
    profile = api_client.get("/api/v1/users/by-handle/ada/").json()
    assert profile["email"] is None and "status" not in profile

    privacy = services.get_privacy_settings(user)
    services.update_settings(privacy, {"profile_visibility": "members", "show_email": True})
    assert api_client.get(f"/api/v1/users/{user.pk}/").status_code == 404
    seen = auth_client(other_user).get(f"/api/v1/users/{user.pk}/").json()
    assert seen["email"] == "ada@example.com"

    services.update_settings(privacy, {"profile_visibility": "private"})
    assert auth_client(other_user).get(f"/api/v1/users/{user.pk}/").status_code == 404
    assert auth_client(user).get(f"/api/v1/users/{user.pk}/").status_code == 200


@pytest.mark.security
def test_hidden_and_missing_profiles_are_indistinguishable(api_client, user):
    services.update_settings(services.get_privacy_settings(user), {"profile_visibility": "private"})
    hidden = api_client.get(f"/api/v1/users/{user.pk}/")
    missing = api_client.get("/api/v1/users/00000000-0000-0000-0000-000000000001/")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json()["error"]["message"] == missing.json()["error"]["message"]


def test_profile_hook_veto(api_client, user):
    from university.core.hooks import Hook, hooks

    def block_everyone(viewer, target):
        return False

    hooks.register(Hook.USER_CAN_VIEW_PROFILE, block_everyone)
    try:
        assert api_client.get(f"/api/v1/users/{user.pk}/").status_code == 404
    finally:
        hooks.unregister(Hook.USER_CAN_VIEW_PROFILE, block_everyone)


def test_settings_endpoints(auth_client, user):
    client = auth_client(user)
    assert (
        client.patch("/api/v1/me/privacy/", {"profile_visibility": "members"}, format="json").json()[
            "profile_visibility"
        ]
        == "members"
    )
    notif = client.patch(
        "/api/v1/me/notifications/",
        {"email_enabled": False, "categories": {"mentions": {"push": False, "bogus": True}}},
        format="json",
    ).json()
    assert notif["email_enabled"] is False and notif["categories"] == {"mentions": {"push": False}}
    sec = client.patch(
        "/api/v1/me/security/", {"login_alerts_enabled": False, "mfa_enabled": True}, format="json"
    ).json()
    assert sec["login_alerts_enabled"] is False and sec["mfa_enabled"] is False  # MFA is read-only here


def test_consents_and_export(auth_client, user):
    client = auth_client(user)
    assert (
        client.post("/api/v1/me/consents/", {"purpose": "marketing", "granted": True}, format="json").status_code == 201
    )
    assert (
        client.post("/api/v1/me/consents/", {"purpose": "selling-data", "granted": True}, format="json").status_code
        == 400
    )
    assert client.get("/api/v1/me/consents/").json()["marketing"]["granted"] is True
    export = client.get("/api/v1/me/export/")
    assert export.status_code == 200
    data = export.json()
    assert data["account"]["email"] == "ada@example.com"
    assert "sessions" in data and "security_activity" in data and "consents" in data
    assert "password" not in str(data).lower().replace("password_changed", "")


# ------------------------------------------------------------ lifecycle
def test_self_deletion_soft_deletes_and_revokes(auth_client, user, api_client):
    client = auth_client(user)
    assert client.delete("/api/v1/me/", {"password": "wrong"}, format="json").status_code == 400
    assert client.delete("/api/v1/me/", {"password": PASSWORD}, format="json").status_code == 204
    user = User.all_objects.get(pk=user.pk)
    assert user.status == UserStatus.DELETED and user.deleted_at is not None
    assert not User.objects.filter(pk=user.pk).exists()  # hidden from normal queries
    assert client.get("/api/v1/me/").status_code == 401
    assert api_client.get(f"/api/v1/users/{user.pk}/").status_code == 404
    login = api_client.post(
        "/api/v1/auth/login/", {"identifier": "ada@example.com", "password": PASSWORD}, format="json"
    )
    assert login.status_code == 401


def test_purge_anonymises_after_grace_period(user):
    import datetime as dt

    from django.utils import timezone

    from university.core.retention import run_retention

    services.delete_account(user, password=PASSWORD)
    assert run_retention(only=["users.deleted_accounts"]) == {"users.deleted_accounts": 0}
    User.all_objects.filter(pk=user.pk).update(deleted_at=timezone.now() - dt.timedelta(days=31))
    assert run_retention(only=["users.deleted_accounts"]) == {"users.deleted_accounts": 1}
    purged = User.all_objects.get(pk=user.pk)
    assert purged.email.endswith("@deleted.invalid") and purged.handle is None and purged.anonymized_at
    assert not purged.has_usable_password()
    assert AuditLog.objects.filter(action="account.purged").exists()


def test_admin_status_actions_require_permission(auth_client, user, other_user, superuser):
    response = auth_client(other_user).post(f"/api/v1/users/{user.pk}/suspend/", {"reason": "spam"}, format="json")
    assert response.status_code == 403
    response = auth_client(superuser).post(f"/api/v1/users/{user.pk}/suspend/", {"reason": "spam"}, format="json")
    assert response.status_code == 204
    user.refresh_from_db()
    assert user.status == UserStatus.SUSPENDED
    login = auth_client(superuser)  # noqa: F841
    assert AuditLog.objects.filter(action="account.suspended", actor=superuser).exists()
    assert auth_client(superuser).post(f"/api/v1/users/{user.pk}/reactivate/", format="json").status_code == 204


def test_cannot_suspend_self_or_superuser(superuser):
    from university.core.exceptions import PermissionDenied
    from university.permissions.services import assign_role

    manager = create_user("manager@example.com", handle="manager")
    assign_role(user=manager, role_key="user_manager")
    with pytest.raises(PermissionDenied):
        services.suspend_user(actor=manager, user=manager, reason="x")
    with pytest.raises(PermissionDenied):
        services.suspend_user(actor=manager, user=superuser, reason="x")


def test_suspension_expires(api_client, user):
    import datetime as dt

    from django.utils import timezone

    User.objects.filter(pk=user.pk).update(
        status=UserStatus.SUSPENDED, is_active=False, suspended_until=timezone.now() - dt.timedelta(minutes=1)
    )
    login = api_client.post("/api/v1/auth/login/", {"identifier": "ada", "password": PASSWORD}, format="json")
    assert login.status_code == 200
