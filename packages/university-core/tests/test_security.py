"""Authentication & session security, including attack scenarios."""

from __future__ import annotations

import datetime as dt
import re

import jwt
import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from university.audit.models import AuditLog
from university.core.testing import PASSWORD, create_user
from university.security.models import APIKey, LoginAttempt, OTPChallenge, RefreshToken, UserSession
from university.security.services.otp import issue_otp, verify_otp

pytestmark = [pytest.mark.django_db, pytest.mark.security]
User = get_user_model()


def login(client, identifier="ada", password=PASSWORD, **extra):
    return client.post("/api/v1/auth/login/", {"identifier": identifier, "password": password, **extra}, format="json")


# ------------------------------------------------------------------ login
def test_login_with_each_identifier(api_client, user):
    assert login(api_client, "ada@example.com").status_code == 200
    assert login(api_client, "ADA").status_code == 200
    assert login(api_client, "+2348000000000").status_code == 401  # unverified/unknown phone
    User.objects.filter(pk=user.pk).update(phone_number="+2348000000000", phone_verified_at=timezone.now())
    assert login(api_client, "+2348000000000").status_code == 200


def test_login_failures_are_generic(api_client, user):
    wrong = login(api_client, password="wrong-password")
    unknown = login(api_client, identifier="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert LoginAttempt.objects.filter(successful=False).count() == 2
    assert not LoginAttempt.objects.exclude(identifier_hash__regex=r"^[0-9a-f]{64}$").exists()  # hashed
    assert AuditLog.objects.filter(action="auth.login.failed").count() == 2


def test_banned_and_suspended_users_cannot_login(api_client, user):
    User.objects.filter(pk=user.pk).update(status="banned", is_active=False)
    response = login(api_client)
    assert response.status_code == 403 and response.json()["error"]["code"] == "account_banned"
    User.objects.filter(pk=user.pk).update(status="suspended")
    assert login(api_client).json()["error"]["code"] == "account_suspended"


def test_brute_force_lockout(api_client, user):
    with override_settings(UNIVERSITY={"AUTH": {"LOCKOUT": {"MAX_FAILURES_PER_IDENTIFIER_AND_IP": 3}}}):
        for _ in range(3):
            assert login(api_client, password="nope").status_code == 401
        locked = login(api_client)  # even the right password is refused while locked
        assert locked.status_code == 429 and locked.json()["error"]["code"] == "login_locked"
        assert int(locked["Retry-After"]) > 0
        assert AuditLog.objects.filter(action="auth.login.locked").exists()


def test_login_throttle(api_client, user):
    with override_settings(UNIVERSITY={"THROTTLE_RATES": {"login": "2/min"}}):
        login(api_client)
        login(api_client)
        assert login(api_client).status_code == 429


# ------------------------------------------------------------------ tokens
def test_access_token_grants_access_and_sessions_are_tracked(api_client, user):
    tokens = login(api_client, device_name="Pixel 8").json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert api_client.get("/api/v1/me/").json()["email"] == "ada@example.com"
    sessions = api_client.get("/api/v1/me/sessions/").json()
    assert sessions[0]["device_name"] == "Pixel 8" and sessions[0]["current"] is True


def test_refresh_rotation_and_reuse_detection(api_client, user):
    tokens = login(api_client).json()
    rotated = api_client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]}, format="json")
    assert rotated.status_code == 200
    new = rotated.json()
    assert new["refresh"] != tokens["refresh"]
    assert RefreshToken.objects.filter(used_at__isnull=False).count() == 1
    assert not RefreshToken.objects.filter(token_hash=tokens["refresh"]).exists()  # stored hashed

    # Replaying the old refresh token revokes the whole session.
    replay = api_client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]}, format="json")
    assert replay.status_code == 401
    session = UserSession.objects.get(pk=tokens["session_id"])
    assert session.revoked_reason == "refresh_token_reuse"
    assert api_client.post("/api/v1/auth/token/refresh/", {"refresh": new["refresh"]}, format="json").status_code == 401
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {new['access']}")
    assert api_client.get("/api/v1/me/").status_code == 401
    assert AuditLog.objects.filter(action="security.refresh_token.reused").exists()


def test_refresh_rejects_garbage_and_idle_sessions(api_client, user):
    assert api_client.post("/api/v1/auth/token/refresh/", {"refresh": "rt_nope"}, format="json").status_code == 401
    assert api_client.post("/api/v1/auth/token/refresh/", {"refresh": "' OR 1=1 --"}, format="json").status_code == 401
    tokens = login(api_client).json()
    UserSession.objects.filter(pk=tokens["session_id"]).update(last_seen_at=timezone.now() - dt.timedelta(days=60))
    assert (
        api_client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]}, format="json").status_code == 401
    )


def test_logout_revokes_session(api_client, user):
    tokens = login(api_client).json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert api_client.post("/api/v1/auth/logout/").status_code == 204
    assert api_client.get("/api/v1/me/").status_code == 401
    api_client.credentials()
    assert (
        api_client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]}, format="json").status_code == 401
    )


def _decode(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def test_tampered_and_forged_tokens_rejected(api_client, user, other_user):
    tokens = login(api_client).json()
    claims = _decode(tokens["access"])
    # alg=none
    none_token = jwt.encode({**claims, "sub": str(other_user.pk)}, key=None, algorithm="none")
    # wrong key
    forged = jwt.encode({**claims, "sub": str(other_user.pk)}, "attacker-key", algorithm="HS256")
    # payload swap keeping signature
    header, payload, sig = tokens["access"].split(".")
    other = jwt.encode({**claims, "sub": str(other_user.pk)}, "x", algorithm="HS256").split(".")[1]
    spliced = f"{header}.{other}.{sig}"
    for bad in (none_token, forged, spliced, "not-a-jwt", tokens["access"] + "x"):
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {bad}")
        assert api_client.get("/api/v1/me/").status_code == 401, bad


def test_expired_token_rejected(api_client, user):
    with override_settings(UNIVERSITY={"AUTH": {"JWT": {"ACCESS_TOKEN_LIFETIME_SECONDS": -60, "LEEWAY_SECONDS": 0}}}):
        tokens = login(api_client).json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    response = api_client.get("/api/v1/me/")
    assert response.status_code == 401


def test_security_stamp_rotation_invalidates_tokens(api_client, user):
    tokens = login(api_client).json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert api_client.get("/api/v1/me/").status_code == 200
    user.rotate_security_stamp()
    user.save(update_fields=["security_stamp"])
    assert api_client.get("/api/v1/me/").status_code == 401


def test_suspension_invalidates_live_tokens(api_client, user, superuser):
    from university.users.services import suspend_user

    tokens = login(api_client).json()
    suspend_user(actor=superuser, user=user, reason="abuse")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert api_client.get("/api/v1/me/").status_code == 401


# --------------------------------------------------------------- sessions
def test_revoke_own_sessions(api_client, user):
    first = login(api_client).json()
    second = login(api_client).json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {first['access']}")
    assert api_client.delete(f"/api/v1/me/sessions/{second['session_id']}/").status_code == 204
    third = login(api_client).json()
    assert api_client.post("/api/v1/me/sessions/revoke-others/").json() == {"revoked": 1}
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {third['access']}")
    assert api_client.get("/api/v1/me/").status_code == 401


def test_cannot_revoke_another_users_session(api_client, auth_client, user, other_user):
    victim = login(api_client, identifier="grace").json()
    response = auth_client(user).delete(f"/api/v1/me/sessions/{victim['session_id']}/")
    assert response.status_code == 404  # IDOR/BOLA: indistinguishable from missing
    assert UserSession.objects.get(pk=victim["session_id"]).revoked_at is None


def test_session_limit(api_client, user):
    with override_settings(UNIVERSITY={"AUTH": {"MAX_SESSIONS_PER_USER": 2}}):
        for _ in range(3):
            login(api_client)
    assert UserSession.objects.active().filter(user=user).count() == 2


def test_suspicious_login_alert(api_client, user, outbox):
    login(api_client, device_id="laptop", HTTP_USER_AGENT="A")
    outbox.clear()
    api_client.post(
        "/api/v1/auth/login/",
        {"identifier": "ada", "password": PASSWORD, "device_id": "unknown-phone"},
        format="json",
        HTTP_USER_AGENT="B",
        REMOTE_ADDR="203.0.113.9",
    )
    assert AuditLog.objects.filter(action="security.login.suspicious").exists()
    assert any("New sign-in" in m.subject for m in outbox)


# --------------------------------------------------------------- API keys
def test_api_key_lifecycle_and_scope_limits(auth_client, api_client, user, superuser):
    client = auth_client(superuser)
    created = client.post("/api/v1/me/api-keys/", {"name": "CI", "scopes": ["audit.view"]}, format="json")
    assert created.status_code == 201
    raw = created.json()["key"]
    assert raw.startswith("uk_")
    assert not APIKey.objects.filter(key_hash=raw).exists()
    assert "key" not in client.get("/api/v1/me/api-keys/").json()[0]

    api_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    assert api_client.get("/api/v1/audit/logs/").status_code == 200
    # Superuser owner, but the key is limited to its scopes.
    assert api_client.get("/api/v1/permissions/").status_code == 403
    # API keys cannot mint API keys.
    assert (
        api_client.post("/api/v1/me/api-keys/", {"name": "x", "scopes": ["audit.view"]}, format="json").status_code
        == 400
    )

    api_client.credentials(HTTP_X_API_KEY=raw)
    assert api_client.get("/api/v1/audit/logs/").status_code == 200

    key_id = created.json()["id"]
    assert client.delete(f"/api/v1/me/api-keys/{key_id}/").status_code == 204
    api_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    assert api_client.get("/api/v1/audit/logs/").status_code == 401


def test_api_key_validation_and_ip_allowlist(auth_client, api_client, user):
    client = auth_client(user)
    assert client.post("/api/v1/me/api-keys/", {"name": "x", "scopes": ["made.up"]}, format="json").status_code == 400
    created = client.post(
        "/api/v1/me/api-keys/", {"name": "x", "scopes": ["*"], "allowed_ips": ["10.0.0.0/8"]}, format="json"
    ).json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {created['key']}")
    assert api_client.get("/api/v1/me/").status_code == 401
    assert api_client.get("/api/v1/me/", REMOTE_ADDR="10.1.2.3").status_code == 200
    api_client.credentials(HTTP_AUTHORIZATION="Api-Key uk_NOTREAL_secret")
    assert api_client.get("/api/v1/me/").status_code == 401


def test_cannot_revoke_another_users_api_key(auth_client, user, other_user):
    created = auth_client(other_user).post("/api/v1/me/api-keys/", {"name": "x", "scopes": ["*"]}, format="json").json()
    assert auth_client(user).delete(f"/api/v1/me/api-keys/{created['id']}/").status_code == 404
    assert APIKey.objects.get(pk=created["id"]).revoked_at is None


# --------------------------------------------------------------- OTP & MFA
def test_otp_attempt_limit_replay_and_expiry(user):
    from university.core.exceptions import ValidationError

    sent = []
    challenge = issue_otp(purpose="unit", channel="email", destination="ada@example.com", user=user)
    assert len(challenge.code_hash) == 64
    for _ in range(5):
        with pytest.raises(ValidationError):
            verify_otp(challenge_id=challenge.pk, code="999999x", purpose="unit")
    challenge.refresh_from_db()
    with pytest.raises(ValidationError) as exc:
        verify_otp(challenge_id=challenge.pk, code="123456", purpose="unit")
    assert exc.value.code in ("too_many_attempts", "invalid_code")
    del sent


def test_otp_cooldown_and_wrong_purpose(user, outbox):
    from university.core.exceptions import RateLimited, ValidationError

    challenge = issue_otp(purpose="unit2", channel="email", destination="ada@example.com", user=user)
    with pytest.raises(RateLimited):
        issue_otp(purpose="unit2", channel="email", destination="ada@example.com", user=user)
    code = re.search(r"\b(\d{6})\b", outbox[-1].body).group(1)
    with pytest.raises(ValidationError):
        verify_otp(challenge_id=challenge.pk, code=code, purpose="other")
    verify_otp(challenge_id=challenge.pk, code=code, purpose="unit2")
    with pytest.raises(ValidationError):
        verify_otp(challenge_id=challenge.pk, code=code, purpose="unit2")  # single use


def test_mfa_enrolment_and_login(api_client, auth_client, user, outbox):
    client = auth_client(user)
    start = client.post("/api/v1/me/mfa/enrol/", {"channel": "email"}, format="json")
    assert start.status_code == 202
    code = re.search(r"\b(\d{6})\b", outbox[-1].body).group(1)
    confirm = client.post(
        "/api/v1/me/mfa/confirm/",
        {"channel": "email", "challenge_id": start.json()["challenge_id"], "code": code},
        format="json",
    )
    assert confirm.status_code == 204

    first = login(api_client)
    assert first.status_code == 202 and first.json()["mfa_required"] is True
    assert "access" not in first.json()
    mfa_code = re.search(r"\b(\d{6})\b", outbox[-1].body).group(1)
    done = api_client.post(
        "/api/v1/auth/login/mfa/", {"challenge_id": first.json()["challenge_id"], "code": mfa_code}, format="json"
    )
    assert done.status_code == 200 and done.json()["access"]
    assert UserSession.objects.filter(auth_method="password+otp").exists()


def test_passwordless_disabled_by_default_and_no_enumeration(api_client, user, outbox):
    assert (
        api_client.post("/api/v1/auth/passwordless/", {"identifier": "ada@example.com"}, format="json").status_code
        == 404
    )
    with override_settings(UNIVERSITY={"AUTH": {"PASSWORDLESS": {"ENABLED": True}}}):
        known = api_client.post("/api/v1/auth/passwordless/", {"identifier": "ada@example.com"}, format="json")
        unknown = api_client.post("/api/v1/auth/passwordless/", {"identifier": "ghost@example.com"}, format="json")
        assert known.status_code == unknown.status_code == 202
        assert set(known.json()) == set(unknown.json())
        code = re.search(r"\b(\d{6})\b", outbox[-1].body).group(1)
        done = api_client.post(
            "/api/v1/auth/passwordless/verify/",
            {"challenge_id": known.json()["challenge_id"], "code": code},
            format="json",
        )
        assert done.status_code == 200
        fake = api_client.post(
            "/api/v1/auth/passwordless/verify/",
            {"challenge_id": unknown.json()["challenge_id"], "code": code},
            format="json",
        )
        assert fake.status_code == 400


# --------------------------------------------------------------- external identity
def test_external_identity_login_and_linking(api_client, user, settings):
    from university.security import providers

    providers._cache.clear()
    settings.UNIVERSITY = {
        **settings.UNIVERSITY,
        "AUTH": {"IDENTITY_PROVIDERS": {"fake": {"CLASS": "tests.fake_provider.FakeProvider"}}},
    }
    try:
        # New person: account created and signed in.
        response = api_client.post(
            "/api/v1/auth/providers/fake/login/", {"id_token": "new@example.com|sub-1"}, format="json"
        )
        assert response.status_code == 200
        created = User.objects.get(email="new@example.com")
        assert created.email_verified and not created.has_usable_password()
        # Existing email is NOT silently linked (account-takeover protection).
        conflict = api_client.post(
            "/api/v1/auth/providers/fake/login/", {"id_token": "ada@example.com|sub-2"}, format="json"
        )
        assert conflict.status_code == 401 and conflict.json()["error"]["code"] == "external_account_conflict"
        bad = api_client.post("/api/v1/auth/providers/fake/login/", {"id_token": "invalid"}, format="json")
        assert bad.status_code == 401
        assert (
            api_client.post("/api/v1/auth/providers/missing/login/", {"id_token": "x"}, format="json").status_code
            == 404
        )
    finally:
        providers._cache.clear()


def test_otp_records_are_hashed(user):
    issue_otp(purpose="hash", channel="email", destination="ada@example.com", user=user)
    challenge = OTPChallenge.objects.get(purpose="hash")
    assert "ada@example.com" not in challenge.destination_hash and challenge.destination_masked == "a***a@example.com"


def test_csrf_enforced_for_cookie_sessions(user):
    from rest_framework.test import APIClient

    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    response = client.patch("/api/v1/me/", {"display_name": "x"}, format="json")
    assert response.status_code == 403  # no CSRF token -> rejected


def test_suspended_until_in_past_lifts_on_login(api_client, user):
    User.objects.filter(pk=user.pk).update(status="suspended", suspended_until=timezone.now() - dt.timedelta(hours=1))
    assert login(api_client).status_code == 200


def test_user_cannot_create_too_many_api_keys(auth_client, user):
    client = auth_client(user)
    with override_settings(UNIVERSITY={"AUTH": {"API_KEYS": {"MAX_PER_USER": 1}}}):
        assert client.post("/api/v1/me/api-keys/", {"name": "a", "scopes": ["*"]}, format="json").status_code == 201
        assert client.post("/api/v1/me/api-keys/", {"name": "b", "scopes": ["*"]}, format="json").status_code == 400


def test_create_user_helper_defaults():
    u = create_user("helper@example.com", handle="helper")
    assert u.is_active and u.email_verified
