"""Core infrastructure: settings, registry, hooks, events, tasks, rate limits, crypto."""

from __future__ import annotations

import io
import uuid

import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import override_settings

from university.core import crypto, ids
from university.core.conf import ModuleSettings, deep_merge, university_settings
from university.core.events import Event, EventBus
from university.core.exceptions import ModuleNotInstalled, RateLimited
from university.core.hooks import HookRegistry
from university.core.logging import REDACTED, redact, redact_text
from university.core.ratelimit import limiter, parse_rate, rate_limit
from university.core.registry import registry
from university.core.serialization import to_jsonable
from university.core.tasks import enqueue, get_task, registered_tasks, task
from university.core.uploads import FileUploadValidator, is_dangerous, sniff_mime_type, uuid_upload_to

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\xdac\xc8\xd5\xb8\t\x00\x02t\x01o\xfbJ\xd2\xe1\x00\x00\x00\x00IEND\xaeB`\x82"  # A real 1x1 PNG: decodes with or without Pillow.


# ----------------------------------------------------------------- settings
def test_deep_merge_preserves_nested_defaults():
    merged = deep_merge({"A": {"x": 1, "y": 2}, "L": [1]}, {"A": {"y": 3}, "L": [2]})
    assert merged == {"A": {"x": 1, "y": 3}, "L": [2]}


def test_settings_defaults_and_overrides():
    assert university_settings.get("AUTH.JWT.ALGORITHM") == "HS256"
    with override_settings(UNIVERSITY={"AUTH": {"JWT": {"ALGORITHM": "HS512"}}}):
        assert university_settings.get("AUTH.JWT.ALGORITHM") == "HS512"
        # untouched siblings keep their defaults
        assert university_settings.get("AUTH.JWT.ISSUER") == "university"
    assert university_settings.get("AUTH.JWT.ALGORITHM") == "HS256"


def test_settings_unknown_key_raises():
    with pytest.raises(AttributeError):
        university_settings.NOT_A_SETTING  # noqa: B018
    with pytest.raises(KeyError):
        university_settings.get("AUTH.NOPE")
    assert university_settings.get("AUTH.NOPE", "fallback") == "fallback"


def test_module_namespace_settings():
    module = ModuleSettings("TESTAPP", {"COLOUR": "blue", "NESTED": {"A": 1}})
    assert module.COLOUR == "blue"
    with override_settings(UNIVERSITY={"TESTAPP": {"NESTED": {"B": 2}}}):
        assert module.NESTED == {"A": 1, "B": 2}


def test_import_from_reports_bad_paths():
    with override_settings(UNIVERSITY={"PROVIDERS": {"EMAIL": "nope.missing.Provider"}}):
        with pytest.raises(ImproperlyConfigured):
            university_settings.import_from("PROVIDERS.EMAIL")


# ----------------------------------------------------------------- ids
def test_uuid_versions():
    assert ids.new_uuid().version == 4
    with override_settings(UNIVERSITY={"IDS": {"UUID_VERSION": 7}}):
        a, b = ids.new_uuid(), ids.new_uuid()
        assert a.version == 7 and b.version == 7
    assert ids.is_valid_uuid(str(uuid.uuid4()))
    assert not ids.is_valid_uuid("1 OR 1=1")


# ----------------------------------------------------------------- registry
def test_registry_discovers_modules_gracefully():
    names = {m.name for m in registry.all()}
    assert {"core", "users", "security", "permissions", "audit", "testapp"} <= names
    assert registry.get("social") is None
    assert not registry.is_installed("marketplace")
    with pytest.raises(ModuleNotInstalled):
        registry.require("marketplace")
    assert registry.get("testapp").version == "9.9.9"
    assert registry.missing_dependencies() == {}


def test_registry_collects_contributions():
    assert "testapp.widgets.view" in registry.permissions
    assert registry.permission_exists("testapp.widgets.*")
    assert not registry.permission_exists("nothing.*")
    assert "school_editor" in registry.roles
    assert {"platform", "school", "club"} <= set(registry.scope_types)
    assert "testapp" in registry.health_checks
    assert "users.deleted_accounts" in registry.retention_policies


# ----------------------------------------------------------------- hooks
def test_hooks_veto_and_collect():
    hooks = HookRegistry()
    assert hooks.allows("x")
    hooks.register("x", lambda: None)
    assert hooks.allows("x")
    hooks.register("x", lambda: False)
    assert not hooks.allows("x")
    hooks.register("c", lambda: {"a": 1}, priority=1)
    hooks.register("c", lambda: {"b": 2})
    assert hooks.collect("c") == {"a": 1, "b": 2}


# ----------------------------------------------------------------- events
def test_event_bus_pattern_matching_and_isolation(settings):
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe("post.*", lambda e: seen.append(e.name))
    bus.subscribe("post.created", lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    settings.UNIVERSITY = {"EVENTS": {"RAISE_HANDLER_ERRORS": False}}
    bus.publish("post.created", {"id": uuid.uuid4()}, on_commit=False)
    bus.publish("comment.created", on_commit=False)
    assert seen == ["post.created"]


def test_event_names_are_validated():
    with pytest.raises(ValueError):
        EventBus().publish("Not Valid", on_commit=False)


@pytest.mark.django_db(transaction=True)
def test_events_dispatch_after_commit_only():
    from tests.testapp.apps import RECEIVED_EVENTS

    RECEIVED_EVENTS.clear()
    from university.core.events import publish

    with pytest.raises(RuntimeError):
        with transaction.atomic():
            publish("testapp.rolled_back", {})
            raise RuntimeError
    assert RECEIVED_EVENTS == []
    with transaction.atomic():
        publish("testapp.committed", {"value": 1})
        assert RECEIVED_EVENTS == []
    assert [e.name for e in RECEIVED_EVENTS] == ["testapp.committed"]
    assert isinstance(RECEIVED_EVENTS[0], Event)


def test_async_handlers_must_be_module_level():
    bus = EventBus()

    def local(event):  # pragma: no cover
        return None

    with pytest.raises(ImproperlyConfigured):
        bus.subscribe("a.b", local, run_async=True)


def test_to_jsonable():
    value = to_jsonable({"id": uuid.UUID(int=1), "n": [1, 2]})
    assert value == {"id": "00000000-0000-0000-0000-000000000001", "n": [1, 2]}
    with pytest.raises(TypeError):
        to_jsonable(object())


# ----------------------------------------------------------------- tasks
@pytest.mark.django_db(transaction=True)
def test_tasks_registered_and_run_on_commit():
    from tests.testapp.tasks import CALLS

    CALLS.clear()
    assert "testapp.record" in registered_tasks()
    with transaction.atomic():
        enqueue("testapp.record", "a", value=2)
        assert CALLS == []
    assert CALLS == [("a", 2)]


def test_task_arguments_must_be_json():
    with pytest.raises(TypeError):
        enqueue("testapp.record", object())


def test_unknown_task():
    with pytest.raises(LookupError):
        get_task("nope")


def test_duplicate_task_names_rejected():
    @task(name="testapp.unique_name_1")
    def one():  # pragma: no cover
        return None

    with pytest.raises(ImproperlyConfigured):

        @task(name="testapp.unique_name_1")
        def two():  # pragma: no cover
            return None


# ----------------------------------------------------------------- rate limiting
@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        ("10/min", (10, 60)),
        ("5/hour", (5, 3600)),
        ("100/15min", (100, 900)),
        ("3/day", (3, 86400)),
        ("5/900s", (5, 900)),
    ],
)
def test_parse_rate(rate, expected):
    assert parse_rate(rate) == expected


def test_parse_rate_rejects_garbage():
    with pytest.raises(ValueError):
        parse_rate("lots")


def test_rate_limit_counts_and_raises():
    for _ in range(3):
        rate_limit("unit", key="k", rate="3/min")
    with pytest.raises(RateLimited) as exc:
        rate_limit("unit", key="k", rate="3/min")
    assert exc.value.retry_after >= 1
    # Different keys are independent.
    rate_limit("unit", key="other", rate="3/min")
    limiter.reset("unit", "k", rate="3/min")
    rate_limit("unit", key="k", rate="3/min")


# ----------------------------------------------------------------- crypto
def test_keyed_hash_purpose_separation_and_rotation(settings):
    a = crypto.keyed_hash("value", purpose="one")
    assert a != crypto.keyed_hash("value", purpose="two")
    assert crypto.verify_keyed_hash("value", a, purpose="one")
    assert not crypto.verify_keyed_hash("other", a, purpose="one")
    settings.UNIVERSITY = {"SECURITY": {"HMAC_KEY": "new-key", "HMAC_KEY_FALLBACKS": [settings.SECRET_KEY]}}
    assert crypto.keyed_hash("value", purpose="one") != a
    assert crypto.verify_keyed_hash("value", a, purpose="one")  # old hash still verifies
    assert a in crypto.keyed_hash_candidates("value", purpose="one")


def test_codes_and_masks():
    code = crypto.generate_numeric_code(6)
    assert len(code) == 6 and code.isdigit()
    assert crypto.mask_email("ada.lovelace@example.com") == "a***e@example.com"
    assert crypto.mask_phone("+2348012345678") == "+234******5678"


def test_log_redaction():
    assert redact({"password": "x", "nested": {"refresh": "y"}, "ok": 1}) == {
        "password": REDACTED,
        "nested": {"refresh": REDACTED},
        "ok": 1,
    }
    assert "abc.def" not in redact_text("Authorization: Bearer abc.def")
    assert "hunter2" not in redact_text("password=hunter2&next=/")


# ----------------------------------------------------------------- uploads
def test_sniffing_and_dangerous_content():
    assert sniff_mime_type(PNG) == "image/png"
    assert sniff_mime_type(b"%PDF-1.7") == "application/pdf"
    assert sniff_mime_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert is_dangerous(b"MZ\x90\x00")
    assert is_dangerous(b"#!/bin/sh\nrm -rf /")
    assert is_dangerous(b"<svg onload=alert(1)>")


def test_upload_validator_rejects_spoofed_content_type():
    validator = FileUploadValidator(allowed_mime_types=["image/png"], max_bytes=1024)
    assert validator(SimpleUploadedFile("a.png", PNG, content_type="image/png")) == "image/png"
    with pytest.raises(ValidationError):
        validator(SimpleUploadedFile("evil.png", b"MZ" + b"\x00" * 30, content_type="image/png"))
    with pytest.raises(ValidationError):
        validator(SimpleUploadedFile("doc.png", b"%PDF-1.4 hello", content_type="image/png"))
    with pytest.raises(ValidationError):
        validator(SimpleUploadedFile("a.exe", PNG, content_type="image/png"))
    with pytest.raises(ValidationError):
        validator(SimpleUploadedFile("big.png", PNG + b"\x00" * 2048, content_type="image/png"))


def test_upload_names_are_random_and_safe():
    upload_to = uuid_upload_to("avatars")
    name = upload_to(None, "../../etc/passwd.png")
    assert name.startswith("avatars/") and ".." not in name and name.endswith(".png")
    assert upload_to(None, "x.ph p").endswith(".bin")
    instance = type("Obj", (), {"_upload_file": io.BytesIO(PNG)})()
    assert uuid_upload_to("a")(instance, "photo.jpg").endswith(".png")


def test_audience_posting_hook_defaults_open_and_can_veto():
    from university.core.audiences import can_post_to, ensure_can_post_to
    from university.core.exceptions import PermissionDenied
    from university.core.hooks import Hook, hooks

    user = object()
    assert can_post_to(user, "community", "c1", "social.post")

    def veto(u, scope_type, scope_id, content_type):
        return False if scope_id == "c1" else None

    hooks.register(Hook.AUDIENCE_CAN_POST, veto)
    try:
        assert not can_post_to(user, "community", "c1", "social.post")
        assert can_post_to(user, "community", "c2", "social.post")
        with pytest.raises(PermissionDenied) as exc:
            ensure_can_post_to(user, "community", "c1", "social.post")
        assert exc.value.code == "audience_posting_restricted"
    finally:
        hooks.unregister(Hook.AUDIENCE_CAN_POST, veto)


def test_content_adapters_must_opt_in_to_moderation(monkeypatch):
    from university.core.checks import check_content_adapters
    from university.core.content import ContentAdapter, content_types, get_moderatable_adapter
    from university.core.exceptions import NotFound
    from university.core.registry import registry

    class DisplayOnly(ContentAdapter):
        content_type = "demo.label"

    class Moderated(ContentAdapter):
        content_type = "demo.item"
        moderatable = True

        def hide(self, object_id, *, reason):
            pass

        def restore(self, object_id):
            pass

        def remove(self, object_id, *, reason):
            pass

    class Incomplete(ContentAdapter):
        content_type = "demo.broken"
        moderatable = True

    adapters = {a.content_type: a for a in (DisplayOnly(), Moderated())}
    monkeypatch.setattr(registry, "_content_adapters", adapters)
    assert ContentAdapter.moderatable is False
    assert content_types() == ["demo.item", "demo.label"]
    assert content_types(moderatable=True) == ["demo.item"]
    assert content_types(moderatable=False) == ["demo.label"]
    assert get_moderatable_adapter("demo.item") is adapters["demo.item"]
    for unknown in ("demo.label", "demo.missing"):
        with pytest.raises(NotFound) as exc:
            get_moderatable_adapter(unknown)
        assert exc.value.message == "Unknown content type."  # Indistinguishable.
    assert check_content_adapters() == []
    monkeypatch.setattr(registry, "_content_adapters", {**adapters, "demo.broken": Incomplete()})
    errors = check_content_adapters()
    assert [e.id for e in errors] == ["university.E003"] and "hide, restore, remove" in errors[0].msg


def test_payable_adapters_are_resolved_by_purpose(monkeypatch):
    from university.core.exceptions import NotFound
    from university.core.payables import Payable, PayableAdapter, get_payable_adapter, payable_purposes
    from university.core.registry import registry

    class Ticket(PayableAdapter):
        purpose = "demo.ticket"

        def resolve(self, object_id, payer):
            return Payable(
                purpose=self.purpose,
                object_id=str(object_id),
                payer_id="p",
                amount_minor=100,
                currency="NGN",
                description="Ticket",
            )

    monkeypatch.setattr(registry, "_payable_adapters", {"demo.ticket": Ticket()})
    assert payable_purposes() == ["demo.ticket"]
    assert get_payable_adapter("demo.ticket").resolve(1, None).amount_minor == 100
    with pytest.raises(NotFound):
        get_payable_adapter("demo.unknown")
    assert Ticket().on_refunded(1, reference="r", amount_minor=1, currency="NGN") is None  # Optional hook.


def test_media_library_contract(monkeypatch):
    from university.core.exceptions import ServiceUnavailable
    from university.core.media import MediaRef, get_media_library, require_media_library
    from university.core.registry import registry

    monkeypatch.setattr(registry, "_media_library", None)
    assert get_media_library() is None
    with pytest.raises(ServiceUnavailable):
        require_media_library()
    sentinel = object()
    monkeypatch.setattr(registry, "_media_library", sentinel)
    assert require_media_library() is sentinel
    ref = MediaRef(id="1", kind="audio", owner_id=None, status="ready", mime_type="audio/mpeg", size=1)
    assert ref.is_ready


def test_more_audio_signatures():
    from university.core.uploads import sniff_mime_type

    assert sniff_mime_type(b"\xff\xf3" + b"\x00" * 30) == "audio/mpeg"
    assert sniff_mime_type(b"\xff\xf1" + b"\x00" * 30) == "audio/aac"


def test_content_adapters_default_to_no_backfill_ids():
    from university.core.content import ContentAdapter
    from university.core.hooks import Hook

    assert list(ContentAdapter().iter_ids()) == []
    assert Hook.CONTENT_TRENDING_SCORES == "content.trending_scores"


def test_entitlements_hook_memoised_and_anonymous_safe(user):
    from django.contrib.auth.models import AnonymousUser

    from university.core import entitlements
    from university.core.exceptions import PermissionDenied
    from university.core.hooks import Hook, hooks

    calls = []

    def provider(u):
        calls.append(u.pk)
        return ["premium.badge", ""]

    hooks.register(Hook.USER_ENTITLEMENTS, provider)
    try:
        assert entitlements.has_entitlement(user, "premium.badge")
        assert not entitlements.has_entitlement(user, "")
        assert entitlements.entitlements(user) == frozenset({"premium.badge"}) and len(calls) == 1
        entitlements.forget(user)
        entitlements.entitlements(user)
        assert len(calls) == 2
        assert not entitlements.has_entitlement(AnonymousUser(), "premium.badge")
        with pytest.raises(PermissionDenied):
            entitlements.ensure_entitlement(user, "premium.other")
    finally:
        hooks.unregister(Hook.USER_ENTITLEMENTS, provider)
