from __future__ import annotations

import datetime as dt
import logging

import pytest
from django.utils import timezone

from tests.content.apps import ITEMS
from university.analytics.models import MetricDaily
from university.core.events import event_bus, publish
from university.permissions.scopes import Scope
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db
BASE = "/api/v1/analytics"
INST = "11111111-1111-4111-8111-111111111111"


def count(metric, scope=("", ""), day=None):
    row = MetricDaily.objects.filter(
        metric=metric, scope_type=scope[0], scope_id=scope[1], date=day or timezone.localdate()
    ).first()
    return row.count if row else 0


def test_events_become_platform_and_scope_counters(user):
    publish(
        "social.post.created",
        {"post_id": "p1", "author_id": user.pk, "scope_type": "institution", "scope_id": INST},
        actor=user,
    )
    publish("social.post.created", {"post_id": "p2", "author_id": user.pk, "visibility": "public"}, actor=user)
    publish("community.member.joined", {"community_id": "c1", "user_id": user.pk}, actor=user)
    assert count("social.post.created") == 2
    assert count("social.post.created", ("institution", INST)) == 1
    assert count("community.member.joined", ("community", "c1")) == 1
    # Excluded and untracked events aren't counted.
    publish("security.login.suspicious", {"user_id": user.pk}, actor=user)
    publish("notifications.notification.created", {"notification_id": "n"})
    publish("somemodule.thing.happened", {"x": 1})
    assert set(MetricDaily.objects.values_list("metric", flat=True)) >= {"social.post.created"}
    assert not MetricDaily.objects.filter(
        metric__in=["security.login.suspicious", "somemodule.thing.happened"]
    ).exists()


@pytest.mark.security
def test_nothing_personal_is_stored(user):
    publish("social.post.created", {"post_id": "p1", "author_id": user.pk}, actor=user)
    stored = str(list(MetricDaily.objects.values()))
    assert str(user.pk) not in stored and "p1" not in stored


def test_active_users_are_unique_per_period(user, other_user):
    for _ in range(3):
        publish("social.post.created", {"post_id": "p"}, actor=user)
    publish("social.post.created", {"post_id": "p"}, actor=other_user)
    today = timezone.localdate()
    assert count("active_users.daily", day=today) == 2
    assert count("active_users.weekly", day=today - dt.timedelta(days=today.weekday())) == 2
    assert count("active_users.monthly", day=today.replace(day=1)) == 2


@pytest.mark.security
def test_views_are_counted_once_and_only_for_visible_content(api_client, auth_client, user, other_user):
    seen = []
    event_bus.subscribe("content.viewed", seen.append)
    try:
        ITEMS["i1"] = {"author": str(user.pk), "label": "Item"}
        client = auth_client(other_user)
        assert client.post(
            f"{BASE}/views/", {"content_type": "test.item", "object_id": "i1"}, format="json"
        ).json() == {"counted": True}
        assert client.post(
            f"{BASE}/views/", {"content_type": "test.item", "object_id": "i1"}, format="json"
        ).json() == {"counted": False}
        assert api_client.post(
            f"{BASE}/views/", {"content_type": "test.item", "object_id": "i1"}, format="json"
        ).json() == {"counted": True}
        assert count("views.test.item") == 2
        # Hidden, unknown and nonexistent are indistinguishable.
        ITEMS["i1"]["hidden_from"] = {str(user.pk)}
        hidden = auth_client(user).post(
            f"{BASE}/views/", {"content_type": "test.item", "object_id": "i1"}, format="json"
        )
        missing = auth_client(user).post(
            f"{BASE}/views/", {"content_type": "test.item", "object_id": "nope"}, format="json"
        )
        unknown = auth_client(user).post(
            f"{BASE}/views/", {"content_type": "nope.nope", "object_id": "i1"}, format="json"
        )
        assert hidden.status_code == missing.status_code == unknown.status_code == 404
        assert all(str(other_user.pk) not in str(e.payload) for e in seen)  # No viewer in the event.
    finally:
        event_bus.unsubscribe("content.viewed", seen.append)


@pytest.mark.security
def test_reports_need_permission_and_suppress_small_counts(auth_client, user, other_user, staff_user):
    for _ in range(3):
        publish("social.post.created", {"post_id": "p", "scope_type": "institution", "scope_id": INST})
    for _ in range(7):
        publish("community.member.joined", {"community_id": "c9", "scope_type": "institution", "scope_id": INST})
    assert auth_client(user).get(f"{BASE}/overview/").status_code == 403
    assign_role(user=staff_user, role_key="analytics_viewer")
    overview = auth_client(staff_user).get(f"{BASE}/overview/", {"metrics": "social.post.created"}).json()
    assert overview["metrics"][0]["total"] == 3  # Platform totals aren't suppressed.
    scope_url = f"{BASE}/scopes/institution/{INST}/"
    assert auth_client(other_user).get(scope_url).status_code == 403
    assign_role(user=other_user, role_key="analytics_viewer", scope=Scope("institution", INST))
    report = auth_client(other_user).get(scope_url).json()
    totals = {m["metric"]: m["total"] for m in report["metrics"]}
    assert totals["social.post.created"] is None  # 3 < 5: suppressed.
    assert totals["community.member.joined"] == 7
    assert report["suppression_threshold"] == 5
    # An institution's viewer can't read another institution.
    other = "22222222-2222-4222-8222-222222222222"
    assert auth_client(other_user).get(f"{BASE}/scopes/institution/{other}/").status_code == 403
    assert (
        auth_client(staff_user).get(f"{BASE}/overview/", {"from": "2020-01-01", "to": "2026-01-01"}).status_code == 400
    )


def test_sinks_receive_minimised_pseudonymous_events(settings, user, caplog):
    settings.UNIVERSITY = {"ANALYTICS": {"SINKS": ["university.analytics.sinks.LogSink"]}}
    with caplog.at_level(logging.INFO, logger="university.analytics.events"):
        publish(
            "social.post.created",
            {"post_id": "secret-post", "author_id": user.pk, "scope_type": "institution", "scope_id": INST},
            actor=user,
        )
    line = next(r.getMessage() for r in caplog.records if r.name == "university.analytics.events")
    assert '"event": "social.post.created"' in line and f'"institution:{INST}"' in line
    assert str(user.pk) not in line and "secret-post" not in line
    import json

    assert len(json.loads(line)["actor"]) == 24


def test_retention(user):
    from university.core.retention import run_retention

    publish("social.post.created", {"post_id": "p"})
    MetricDaily.objects.update(date=timezone.localdate() - dt.timedelta(days=2000))
    assert run_retention(only=["analytics.daily_metrics"])["analytics.daily_metrics"] >= 1
    assert not MetricDaily.objects.exists()


def test_exclusions_win_over_tracking(user):
    # "events.*" is tracked, but per-attendee notices are excluded.
    publish("events.attendee.notice", {"event_id": "e1", "user_id": user.pk, "kind": "reminder"})
    publish("events.event.published", {"event_id": "e1"})
    assert count("events.event.published") == 1
    assert not MetricDaily.objects.filter(metric="events.attendee.notice").exists()
