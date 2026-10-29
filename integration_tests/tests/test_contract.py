"""The published OpenAPI schema tells the truth.

A realistic world is built through the API, then every GET endpoint in the schema is called (as the
owner of the data and as an administrator) and each JSON response is validated against the schema
the platform publishes. Client generators (openapi-typescript, openapi-generator...) trust this
schema, so a page object documented as a bare array, or a field left out, is a bug.
"""

from __future__ import annotations

import datetime as dt
import io
import re
import uuid
from typing import Any

import jsonschema
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator

from tests.test_commerce import checkout, provider_confirms
from university.core.testing import authenticate, create_user
from university.creator.services import sync_categories as sync_creator_categories
from university.institution.models import Institution, InstitutionMembership, InstitutionType
from university.institution.services import request_membership
from university.marketplace.services import sync_categories as sync_market_categories
from university.payments.providers import reset_providers
from university.payments.providers import testing as gateway
from university.trending.services import compute_trending

pytestmark = pytest.mark.django_db

# Responses that are free-form by nature (each installed module contributes its own keys).
FREE_FORM = {
    "/api/v1/me/export/": "a data export holds whatever each installed module stores",
    "/api/v1/analytics/overview/": "metrics depend on the installed modules",
    "/api/v1/analytics/scopes/{scope_type}/{scope_id}/": "metrics depend on the installed modules",
    "/api/v1/me/creator/analytics/": "per-network breakdowns vary by linked provider",
    "/api/v1/campaigns/{campaign_id}/analytics/": "per-network breakdowns vary by linked provider",
    "/api/v1/institutions/{institution_id}/{kind}/{object_id}/": "polymorphic by kind (campus, unit, programme...)",
}

# Endpoints that don't answer with JSON (files, feeds, redirects).
NON_JSON = re.compile(r"(\.ics|\.xml|\.csv|\.vtt|/stream/|/files/|/cover/|/document/|/media-kit/$|/schema)")


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (109, 40, 217)).save(buffer, format="PNG")
    return buffer.getvalue()


# ------------------------------------------------------------------ the world
@pytest.fixture
def world(settings, api_client):
    from rest_framework.test import APIClient

    gateway.reset()
    reset_providers()
    sync_market_categories()
    sync_creator_categories()
    settings.UNIVERSITY = {
        "PAYMENTS": {
            "PROVIDERS": {"test": {"class": "university.payments.providers.testing.TestPaymentProvider"}},
            "DEFAULT_PROVIDER": "test",
        },
        "EVENTS": {"PAID_TICKETS_ENABLED": True},
        "PROMOTIONS": {"REQUIRE_PAYMENT": False},
    }
    aged = timezone.now() - dt.timedelta(days=60)
    alice = create_user("alice@example.com", handle="alice", display_name="Alice Obi")
    bob = create_user("bob@example.com", handle="bob", display_name="Bob Ade")
    admin = create_user("admin@example.com", handle="platform_admin", is_staff=True, is_superuser=True)
    type(alice).objects.filter(pk__in=[alice.pk, bob.pk]).update(created_at=aged)

    def client(user):
        c = APIClient()
        authenticate(c, user)
        return c

    a, b, root = client(alice), client(bob), client(admin)

    def ok(response, *codes):
        assert response.status_code in (codes or (200, 201)), (response.status_code, response.content[:500])
        return response.json() if response.content else {}

    uni = Institution.objects.create(
        name="Example University",
        short_name="EXU",
        slug="exu",
        country="NG",
        type=InstitutionType.objects.get(key="university"),
    )
    membership = request_membership(user=alice, institution=uni, role="student")
    InstitutionMembership.objects.filter(pk=membership.pk).update(status="verified")

    # Social
    post = ok(
        a.post(
            "/api/v1/social/posts/",
            {"body": "Hackathon at #EXU this weekend!", "visibility": "public", "poll": {"options": ["Yes", "No"]}},
            format="json",
        )
    )
    comment = ok(b.post(f"/api/v1/social/posts/{post['id']}/comments/", {"body": "Count me in"}, format="json"))
    ok(b.post(f"/api/v1/social/posts/{post['id']}/reaction/", {"kind": "like"}, format="json"))
    ok(b.post(f"/api/v1/social/posts/{post['id']}/bookmark/"), 200, 201, 204)
    ok(b.post(f"/api/v1/social/posts/{post['id']}/repost/", {}, format="json"))
    ok(b.post(f"/api/v1/social/users/{alice.pk}/follow/"))
    ok(a.post(f"/api/v1/social/users/{bob.pk}/follow/"))
    media = ok(
        a.post(
            "/api/v1/social/media/",
            {"file": SimpleUploadedFile("pic.png", _png()), "alt_text": "Gate"},
            format="multipart",
        )
    )
    ok(
        a.post(
            "/api/v1/social/posts/",
            {"body": "With a photo", "visibility": "public", "media": [media["id"]]},
            format="json",
        )
    )
    ok(a.post("/api/v1/me/avatar/", {"file": SimpleUploadedFile("me.png", _png())}, format="multipart"))

    # Communities and anonymous gist
    community = ok(
        a.post("/api/v1/communities/", {"name": "Tech Gist", "description": "Code", "privacy": "public"}, format="json")
    )
    ok(b.post(f"/api/v1/communities/{community['id']}/join/"), 200, 201, 202)
    ok(
        a.post(
            "/api/v1/social/posts/",
            {"body": "Welcome!", "visibility": "community", "audience_id": community["id"]},
            format="json",
        )
    )
    gist = ok(
        b.post(
            "/api/v1/anonymous/posts/",
            {"body": "Confession time", "visibility": "community", "audience_id": community["id"]},
            format="json",
        )
    )
    ok(a.post(f"/api/v1/anonymous/posts/{gist['id']}/comments/", {"body": "Same"}, format="json"))

    # Events (free and paid)
    starts = timezone.now() + dt.timedelta(days=5)
    event = ok(
        a.post(
            "/api/v1/events/",
            {
                "title": "Hackathon",
                "summary": "Build",
                "location_details": "Hall A",
                "capacity": 50,
                "starts_at": starts.isoformat(),
                "ends_at": (starts + dt.timedelta(hours=6)).isoformat(),
            },
            format="json",
        )
    )
    ok(a.post(f"/api/v1/events/{event['id']}/publish/"))
    ok(
        a.post(
            f"/api/v1/events/{event['id']}/sessions/",
            {
                "title": "Kick-off",
                "starts_at": starts.isoformat(),
                "ends_at": (starts + dt.timedelta(hours=1)).isoformat(),
            },
            format="json",
        )
    )
    registration = ok(b.post(f"/api/v1/events/{event['id']}/register/", {}, format="json"))
    event = ok(a.get(f"/api/v1/events/{event['id']}/"))

    # Marketplace with a paid order
    listing = ok(
        a.post(
            "/api/v1/marketplace/listings/",
            {"title": "Casio fx-991ES", "category": "accessories", "price_minor": 1500000, "quantity": 3},
            format="json",
        )
    )
    ok(
        a.post(
            f"/api/v1/marketplace/listings/{listing['id']}/images/",
            {"file": SimpleUploadedFile("calc.png", _png())},
            format="multipart",
        )
    )
    ok(a.post(f"/api/v1/marketplace/listings/{listing['id']}/status/", {"action": "publish"}, format="json"))
    order = ok(
        b.post(
            "/api/v1/marketplace/orders/",
            {"listing": listing["id"]},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
    )
    intent = checkout(b, "marketplace.order", order["id"])
    provider_confirms(api_client, intent)

    # Podcasts
    show = ok(
        a.post(
            "/api/v1/podcasts/",
            {"title": "Build in Public", "description": "Founders", "category": "Technology", "language": "en"},
            format="json",
        )
    )
    ok(a.post(f"/api/v1/podcasts/{show['id']}/status/", {"action": "publish"}, format="json"))
    episode = ok(
        a.post(f"/api/v1/podcasts/{show['id']}/episodes/", {"title": "Pilot", "summary": "First"}, format="json")
    )
    ok(b.post(f"/api/v1/podcasts/{show['id']}/subscription/"), 200, 201, 204)

    # Institution announcements and the anonymous inbox
    announcement = ok(
        root.post(
            f"/api/v1/institutions/{uni.pk}/announcements/",
            {"title": "Exams", "body": "Timetable is out", "audience": "public", "publish": True},
            format="json",
        )
    )
    ok(a.patch("/api/v1/anonymous/me/inbox/", {"enabled": True, "prompt": "Ask me"}, format="json"))
    ok(b.post("/api/v1/anonymous/inboxes/alice/messages/", {"body": "Favourite spot?"}, format="json"), 202)
    inbox_message = a.get("/api/v1/anonymous/me/inbox/messages/").json()["results"][0]
    ok(
        a.post(
            f"/api/v1/anonymous/me/inbox/messages/{inbox_message['id']}/answer/",
            {"answer": "Library", "public": True},
            format="json",
        )
    )

    # Opportunities
    opportunity = ok(
        a.post(
            "/api/v1/opportunities/",
            {
                "kind": "internship",
                "title": "Intern",
                "organization_name": "Acme",
                "description": "Build things",
                "publish": True,
            },
            format="json",
        )
    )
    application = ok(b.post(f"/api/v1/opportunities/{opportunity['id']}/apply/", {"cover_note": "Hi"}, format="json"))
    ok(b.post(f"/api/v1/opportunities/{opportunity['id']}/save/"), 204)

    # Messaging
    conversation = ok(
        a.post("/api/v1/messaging/conversations/", {"participant_ids": [str(bob.pk)], "body": "Hi Bob"}, format="json")
    )
    ok(b.post(f"/api/v1/messaging/conversations/{conversation['id']}/messages/", {"body": "Hi Alice"}, format="json"))

    # Promotions: an approved ad, served and tracked
    campaign = ok(
        a.post(
            "/api/v1/promotions/campaigns/",
            {
                "name": "Launch",
                "kind": "ad",
                "headline": "Try it",
                "body": "New on campus",
                "destination_url": "https://example.com/",
                "placements": ["feed"],
                "starts_at": (timezone.now() - dt.timedelta(minutes=1)).isoformat(),
                "ends_at": (timezone.now() + dt.timedelta(days=3)).isoformat(),
                "budget_minor": 500000,
                "currency": "NGN",
            },
            format="json",
        )
    )
    ok(a.post(f"/api/v1/promotions/campaigns/{campaign['id']}/submit/"))
    ok(root.post(f"/api/v1/promotions/campaigns/{campaign['id']}/review/", {"approve": True}, format="json"))
    served = ok(b.get("/api/v1/promotions/serve/", {"placement": "feed"}))
    assert served and served[0]["label"] == "Sponsored"
    ok(b.post("/api/v1/promotions/impressions/", {"token": served[0]["token"]}, format="json"), 204)

    # Subscriptions: Bob subscribes and pays through the test provider
    subscription = ok(b.post("/api/v1/subscriptions/me/", {"plan": "plus", "interval": "month"}, format="json"))
    due = subscription["payment_due"]
    intent = ok(
        b.post(
            "/api/v1/payments/checkout/",
            {"purpose": due["purpose"], "object_id": due["object_id"]},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
    )
    gateway.mark_paid(intent["reference"], intent["amount_minor"], "NGN")
    ok(b.post(f"/api/v1/payments/{intent['reference']}/verify/", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())))
    assert b.get("/api/v1/subscriptions/me/").json()["subscription"]["status"] == "active"

    # Creator, moderation, discovery
    ok(a.post("/api/v1/me/creator/", {"display_name": "Alice Creates", "bio": "Skits"}, format="json"), 200, 201)
    ok(
        b.post(
            "/api/v1/moderation/reports/",
            {"content_type": "social.post", "object_id": post["id"], "reason": "spam"},
            format="json",
        ),
        200,
        201,
        202,
    )
    compute_trending()
    notification = (b.get("/api/v1/notifications/").json()["results"] or [{}])[0]

    return {
        "clients": {"owner": a, "member": b, "admin": root},
        "params": {
            "post_id": post["id"],
            "object_id": post["id"],
            "comment_id": comment["id"],
            "user_id": str(alice.pk),
            "campaign_id": campaign["id"],
            "handle": "alice",
            "lookup": "alice",
            "community_id": community["id"],
            "event_id": event["id"],
            "registration_id": registration["id"],
            "listing_id": listing["id"],
            "order_id": order["id"],
            "reference": intent["reference"],
            "podcast_id": show["id"],
            "episode_id": episode["id"],
            "institution_id": str(uni.pk),
            "announcement_id": announcement["id"],
            "conversation_id": conversation["id"],
            "opportunity_id": opportunity["id"],
            "application_id": application["id"],
            "message_id": inbox_message["id"],
            "membership_id": str(membership.pk),
            "notification_id": notification.get("id", str(uuid.uuid4())),
            "tag": "exu",
            "name": "explore",
            "scope_type": "community",
            "scope_id": community["id"],
        },
        "slugs": {"events": event["slug"], "podcasts": show["slug"]},
        # Gist is readable only by members of its audience: read it as its author and as another member.
        "owners": {"/api/v1/anonymous/": {"author": b, "member": a, "public": APIClient()}},
    }


# ------------------------------------------------------------------ schema → JSON Schema
def _convert(node: Any) -> Any:
    """OpenAPI 3.0 schema → JSON Schema (draft 7): refs to definitions, nullable → null union."""
    if isinstance(node, list):
        return [_convert(item) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return {"$ref": "#/definitions/" + node["$ref"].rsplit("/", 1)[-1]}
    out = {
        k: _convert(v)
        for k, v in node.items()
        if k not in {"nullable", "readOnly", "writeOnly", "example", "discriminator"}
    }
    if "oneOf" in out:  # Formats aren't asserted, so overlapping branches (e.g. blank-or-URL) are expected.
        out["anyOf"] = out.pop("oneOf")
    if node.get("nullable"):
        return {"anyOf": [out, {"type": "null"}]}
    return out


@pytest.fixture(scope="module")
def schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def _validator(schema: dict, response_schema: dict) -> jsonschema.Draft7Validator:
    definitions = {name: _convert(s) for name, s in schema["components"]["schemas"].items()}
    return jsonschema.Draft7Validator({**_convert(response_schema), "definitions": definitions})


def _free_form(schema: dict, node: dict) -> bool:
    if "$ref" in node:
        node = schema["components"]["schemas"][node["$ref"].rsplit("/", 1)[-1]]
    has_shape = node.get("properties") or node.get("allOf") or isinstance(node.get("additionalProperties"), dict)
    return node.get("type") == "object" and not has_shape


def _fill(path: str, params: dict[str, str], slugs: dict[str, str]) -> str | None:
    def value(match: re.Match) -> str:
        name = match.group(1)
        if name == "slug":
            return slugs["events" if "/events/" in path else "podcasts"]
        if name not in params:
            raise KeyError(name)
        return params[name]

    try:
        return re.sub(r"\{(\w+)\}", value, path)
    except KeyError:
        return None


def test_every_get_response_matches_the_published_schema(world, schema):
    problems: list[str] = []
    checked, skipped = 0, []
    for path, operations in sorted(schema["paths"].items()):
        op = operations.get("get")
        if not op or NON_JSON.search(path):
            continue
        url = _fill(path, world["params"], world["slugs"])
        if url is None:
            skipped.append(path)
            continue
        response_schema = op["responses"].get("200", {}).get("content", {}).get("application/json", {}).get("schema")
        if response_schema is None:
            continue
        if _free_form(schema, response_schema) and path not in FREE_FORM:
            problems.append(f"{path}: response is undocumented (a free-form object)")
            continue
        validator = _validator(schema, response_schema)
        callers = dict(world["clients"])
        for prefix, clients in world["owners"].items():
            if path.startswith(prefix):
                callers = clients
        for who, client in callers.items():
            response = client.get(url)
            if response.status_code != 200 or not response.get("Content-Type", "").startswith("application/json"):
                continue
            checked += 1
            for error in sorted(validator.iter_errors(response.json()), key=str)[:2]:
                where = "/".join(str(p) for p in error.absolute_path) or "(root)"
                problems.append(f"{path} [{who}] at {where}: {error.message[:160]}")
    assert checked > 120, f"Only {checked} responses checked; the world fixture needs more data. Skipped: {skipped}"
    assert not problems, f"{len(problems)} schema mismatches:\n" + "\n".join(problems)
