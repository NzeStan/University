from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from tests.content.apps import ITEMS
from university.core.events import publish
from university.core.hooks import Hook, hooks
from university.core.testing import create_user
from university.trending import services
from university.trending.algorithms import GravityVelocity, ItemStats
from university.trending.conf import trending_settings
from university.trending.models import ACTORS_SIGNAL, TrendingScore, TrendingSignal

pytestmark = pytest.mark.django_db


def people(n):
    return [create_user(f"p{i}@example.com", handle=f"person{i}") for i in range(n)]


def like(item_id, user):
    publish("test.item.liked", {"item_id": item_id}, actor=user)


def signals(item_id, signal, count, hours_ago):
    hour = (timezone.now() - dt.timedelta(hours=hours_ago)).replace(minute=0, second=0, microsecond=0)
    TrendingSignal.objects.create(content_type="test.item", object_id=item_id, signal=signal, hour=hour, count=count)


def test_velocity_beats_total_likes():
    created = timezone.now() - dt.timedelta(hours=20)
    ITEMS["old"] = {"author": "a1", "label": "Old favourite", "created_at": created}
    ITEMS["rising"] = {"author": "a2", "label": "Rising now", "created_at": created}
    signals("old", "reaction", 10, hours_ago=30)  # More likes in total, but long ago.
    signals("old", ACTORS_SIGNAL, 10, hours_ago=30)
    signals("rising", "reaction", 6, hours_ago=1)
    signals("rising", ACTORS_SIGNAL, 6, hours_ago=1)
    services.compute_trending()
    ranked = list(TrendingScore.objects.order_by("-score").values_list("object_id", flat=True))
    assert ranked == ["rising", "old"]


def test_engagement_weights_and_recency():
    algorithm = GravityVelocity(trending_settings)
    shares = ItemStats(window={"share": 2}, recent={"share": 0}, unique_actors=2, age_hours=10)
    likes = ItemStats(window={"reaction": 2}, recent={"reaction": 0}, unique_actors=2, age_hours=10)
    assert algorithm.score(shares) > algorithm.score(likes)  # Shares weigh more than likes.
    newer = ItemStats(window={"reaction": 2}, recent={"reaction": 0}, unique_actors=2, age_hours=1)
    assert algorithm.score(newer) > algorithm.score(likes)  # Recency.
    lonely = ItemStats(window={"reaction": 50}, recent={"reaction": 50}, unique_actors=1, age_hours=1)
    assert algorithm.score(lonely) == 0  # One account can't make something trend.


@pytest.mark.security
def test_one_person_cannot_pump_an_item():
    ITEMS["x"] = {"author": "a", "label": "X"}
    pumper, *others = people(3)
    for _ in range(5):
        like("x", pumper)
    rows = dict(TrendingSignal.objects.filter(object_id="x").values_list("signal", "count"))
    assert rows == {"reaction": 1, ACTORS_SIGNAL: 1}
    assert services.compute_trending() == 0  # Below MIN_UNIQUE_ACTORS.
    like("x", others[0])
    publish("test.item.shared", {"item_id": "x"}, actor=others[1])
    assert services.compute_trending() == 1


@pytest.mark.security
def test_lists_are_permission_aware_and_diverse(api_client, auth_client, user):
    crowd = people(3)
    for key, author in (("a1", "same"), ("a2", "same"), ("a3", "same"), ("b1", "other"), ("secret", "other")):
        ITEMS[key] = {"author": author, "label": f"Item {key}"}
        for person in crowd:
            like(key, person)
    ITEMS["secret"]["hidden_from"] = {str(user.pk)}
    services.compute_trending()
    listed = [i["object_id"] for i in auth_client(user).get("/api/v1/trending/").json()]
    assert "secret" not in listed  # Not visible to this viewer.
    assert len([i for i in listed if i.startswith("a")]) == 2  # At most two per author.
    assert "b1" in listed
    anonymous = [i["object_id"] for i in api_client.get("/api/v1/trending/", {"type": "test.item", "limit": 50}).json()]
    assert "secret" in anonymous and all(
        set(i) >= {"title", "score"} for i in api_client.get("/api/v1/trending/").json()
    )


def test_scoped_trending_and_feed_hook():
    crowd = people(2)
    ITEMS["campus"] = {"author": "a", "label": "Campus news", "scope": ("institution", "inst-1")}
    ITEMS["global"] = {"author": "b", "label": "Global"}
    for key in ("campus", "global"):
        for person in crowd:
            like(key, person)
    services.compute_trending()
    scoped = services.trending(viewer=None, scope=("institution", "inst-1"))
    assert [i["object_id"] for i in scoped] == ["campus"]
    scores = hooks.collect(Hook.CONTENT_TRENDING_SCORES, "test.item", ["campus", "nope"])
    assert set(scores) == {"campus"} and scores["campus"] > 0


def test_retention():
    from university.core.retention import run_retention

    signals("old", "reaction", 1, hours_ago=500)
    assert run_retention(only=["trending.signals"])["trending.signals"] == 1
