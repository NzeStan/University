"""API infrastructure: error envelope, request ids, headers, health, idempotency, webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from django.test import override_settings

from tests.testapp import state, views
from university.core.models import IdempotencyRecord, WebhookEvent

pytestmark = pytest.mark.django_db


def test_error_envelope_for_unauthenticated(api_client):
    response = api_client.get("/api/v1/me/")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "not_authenticated"
    assert body["error"]["request_id"] == response["X-Request-ID"]


def test_validation_errors_use_envelope(api_client):
    response = api_client.post("/api/v1/auth/login/", {}, format="json")
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid"
    assert "identifier" in error["details"]


def test_unhandled_errors_do_not_leak(api_client):
    response = api_client.get("/api/v1/testapp/boom/")
    assert response.status_code == 500
    text = response.content.decode()
    assert "passwd" not in text and "Traceback" not in text
    assert response.json()["error"]["code"] == "server_error"


def test_request_id_generated_and_untrusted_input_ignored(api_client):
    response = api_client.get("/health/", HTTP_X_REQUEST_ID="attacker-chosen-id")
    assert response["X-Request-ID"] != "attacker-chosen-id"
    with override_settings(UNIVERSITY={"SECURITY": {"TRUST_INCOMING_REQUEST_ID": True}}):
        response = api_client.get("/health/", HTTP_X_REQUEST_ID="edge-request-1234")
        assert response["X-Request-ID"] == "edge-request-1234"
        response = api_client.get("/health/", HTTP_X_REQUEST_ID="bad id\n")
        assert response["X-Request-ID"] != "bad id\n"


def test_api_security_headers(auth_client, user):
    response = auth_client(user).get("/api/v1/me/")
    assert response["Cache-Control"] == "no-store"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'none'" in response["Content-Security-Policy"]


def test_health_endpoints(api_client):
    assert api_client.get("/health/").json() == {"status": "ok"}
    assert api_client.get("/health/live/").status_code == 200
    ready = api_client.get("/health/ready/")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok", "cache": "ok", "testapp": "ok"}
    state.HEALTHY = False
    try:
        ready = api_client.get("/health/ready/")
        assert ready.status_code == 503
        assert ready.json()["checks"]["testapp"] == "fail"
    finally:
        state.HEALTHY = True


def test_modules_endpoint_hides_versions_from_public(api_client, auth_client, staff_user):
    public = api_client.get("/api/v1/meta/modules/").json()
    assert {"name": "testapp"} in public
    staff = auth_client(staff_user).get("/api/v1/meta/modules/").json()
    assert {"name": "testapp", "version": "9.9.9"} in staff


def test_global_and_scoped_throttles(api_client):
    with override_settings(UNIVERSITY={"THROTTLE_RATES": {"testapp_public": "2/min"}}):
        assert api_client.get("/api/v1/testapp/public/").status_code == 200
        assert api_client.get("/api/v1/testapp/public/").status_code == 200
        response = api_client.get("/api/v1/testapp/public/")
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "rate_limited"
        assert int(response["Retry-After"]) >= 1
    with override_settings(UNIVERSITY={"THROTTLE_RATES": {"anon_global": "1/min"}}):
        api_client.get("/api/v1/meta/modules/")
        assert api_client.get("/api/v1/meta/modules/").status_code == 429


# ------------------------------------------------------------ idempotency
def test_idempotent_replay(auth_client, user):
    client = auth_client(user)
    first = client.post("/api/v1/testapp/orders/", {"item": "book"}, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    second = client.post("/api/v1/testapp/orders/", {"item": "book"}, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert second["Idempotent-Replayed"] == "true"
    assert IdempotencyRecord.objects.count() == 1


def test_idempotency_key_reuse_with_different_payload(auth_client, user):
    client = auth_client(user)
    client.post("/api/v1/testapp/orders/", {"item": "book"}, format="json", HTTP_IDEMPOTENCY_KEY="k2")
    response = client.post("/api/v1/testapp/orders/", {"item": "pen"}, format="json", HTTP_IDEMPOTENCY_KEY="k2")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "idempotency_key_reused"


def test_idempotency_is_scoped_per_user(auth_client, user, other_user):
    a = auth_client(user).post("/api/v1/testapp/orders/", {"item": "x"}, format="json", HTTP_IDEMPOTENCY_KEY="shared")
    b = auth_client(other_user).post(
        "/api/v1/testapp/orders/", {"item": "x"}, format="json", HTTP_IDEMPOTENCY_KEY="shared"
    )
    assert a.json()["order"] != b.json()["order"]
    assert "Idempotent-Replayed" not in b


def test_idempotency_in_progress_conflict(auth_client, user):
    import datetime as dt

    from django.utils import timezone

    body = json.dumps({"item": "x"}, sort_keys=True)
    IdempotencyRecord.objects.create(
        user=user,
        scope="testapp.order.create",
        key="busy",
        fingerprint=hashlib.sha256(f"POST\n/api/v1/testapp/orders/\n{body}".encode()).hexdigest(),
        locked_until=timezone.now() + dt.timedelta(seconds=30),
    )
    response = auth_client(user).post(
        "/api/v1/testapp/orders/", {"item": "x"}, format="json", HTTP_IDEMPOTENCY_KEY="busy"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_in_progress"


def test_failed_requests_are_not_stored(auth_client, user):
    client = auth_client(user)
    response = client.post("/api/v1/testapp/orders/", {"fail": "conflict"}, format="json", HTTP_IDEMPOTENCY_KEY="k3")
    assert response.status_code == 409
    assert not IdempotencyRecord.objects.filter(key="k3").exists()


# --------------------------------------------------------------- webhooks
def _signed(payload: dict, *, secret: str = views.WEBHOOK_SECRET, ts: int | None = None):
    body = json.dumps(payload).encode()
    ts = ts if ts is not None else int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{body.decode()}".encode(), hashlib.sha256).hexdigest()
    return body, {"HTTP_X_SIGNATURE": sig, "HTTP_X_TIMESTAMP": str(ts)}


def test_webhook_verified_processed_and_deduplicated(api_client):
    views.HANDLED.clear()
    body, headers = _signed({"id": "evt_1", "type": "charge.success"})
    first = api_client.post("/api/v1/testapp/webhook/", body, content_type="application/json", **headers)
    assert first.status_code == 200 and first.json() == {"status": "processed"}
    replay = api_client.post("/api/v1/testapp/webhook/", body, content_type="application/json", **headers)
    assert replay.json() == {"status": "duplicate"}
    assert views.HANDLED == ["evt_1"]
    event = WebhookEvent.objects.get(external_id="evt_1")
    assert event.status == WebhookEvent.Status.PROCESSED and event.attempts == 2


@pytest.mark.security
def test_webhook_rejects_bad_signature_and_stale_timestamp(api_client):
    body, headers = _signed({"id": "evt_2"}, secret="wrong")
    assert (
        api_client.post("/api/v1/testapp/webhook/", body, content_type="application/json", **headers).status_code == 400
    )
    body, headers = _signed({"id": "evt_3"}, ts=int(time.time()) - 3600)
    response = api_client.post("/api/v1/testapp/webhook/", body, content_type="application/json", **headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "stale_webhook"
    assert not WebhookEvent.objects.exists()


def test_openapi_schema_generates(api_client):
    response = api_client.get("/api/schema/", HTTP_ACCEPT="application/vnd.oai.openapi+json")
    assert response.status_code == 200
    schema = json.loads(response.content)
    assert "/api/v1/auth/login/" in schema["paths"]
    assert "BearerAuth" in schema["components"]["securitySchemes"]
