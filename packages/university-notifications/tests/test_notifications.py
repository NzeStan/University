from __future__ import annotations

import datetime as dt
import uuid

import pytest
from django.utils import timezone

from tests.content import push as recording
from tests.content.apps import BLOCKS, ITEMS
from university.core.events import publish
from university.core.testing import create_user
from university.notifications import services
from university.notifications.constants import DeliveryStatus
from university.notifications.delivery import deliver, send_digests
from university.notifications.models import Delivery, Notification, PushDevice
from university.users.services.preferences import get_notification_settings

BASE = "/api/v1/notifications"
TOKEN = "fcm-token-" + "x" * 40

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _recording_push(settings):
    recording.SENT.clear()
    recording.BEHAVIOUR["mode"] = "ok"
    settings.UNIVERSITY = {
        "NOTIFICATIONS": {"PUSH_PROVIDER": "tests.content.push.RecordingPushProvider"},
    }
    yield
    recording.SENT.clear()


def mention(author, mentioned, comment_id=None):
    comment_id = comment_id or uuid.uuid4()
    publish(
        "social.mention.created",
        {"post_id": uuid.uuid4(), "comment_id": comment_id, "author_id": author.pk, "mentioned_user_id": mentioned.pk},
        actor=author,
    )
    return comment_id


def react(post_author, reactor, post_id):
    publish(
        "social.post.reacted",
        {"post_id": post_id, "post_author_id": post_author.pk, "user_id": reactor.pk, "kind": "like"},
        actor=reactor,
    )


def feed(client, **params):
    response = client.get(f"{BASE}/", params)
    assert response.status_code == 200
    return response.json()["results"]


def prefs(user, **changes):
    settings_row = get_notification_settings(user)
    for key, value in changes.items():
        setattr(settings_row, key, value)
    settings_row.save()
    return settings_row


def register(client, token=TOKEN, platform="android"):
    return client.post(f"{BASE}/devices/", {"platform": platform, "token": token, "name": "Pixel"}, format="json")


# --------------------------------------------------------------- creation
def test_mention_appears_in_feed_rendered_at_read_time(auth_client, user, other_user):
    mention(other_user, user)
    items = feed(auth_client(user))
    assert len(items) == 1
    item = items[0]
    assert item["verb"] == "social.mention" and item["category"] == "mentions"
    assert item["title"] == "@grace mentioned you"
    assert item["actor"]["handle"] == "grace"
    assert item["target"]["type"] == "social.comment"
    assert item["is_read"] is False and item["url"].endswith(item["id"])
    # The actor's *current* name is used: no stale copies.
    other_user.display_name = "Grace Hopper"
    other_user.save()
    assert feed(auth_client(user))[0]["title"] == "Grace Hopper mentioned you"


@pytest.mark.security
def test_no_self_inactive_or_blocked_notifications(auth_client, user, other_user, third_user):
    mention(user, user)
    assert not Notification.objects.exists()
    BLOCKS.add((str(user.pk), str(other_user.pk)))
    mention(other_user, user)
    assert not Notification.objects.exists()
    third_user.status = "suspended"
    third_user.save()
    mention(third_user, user)
    assert not Notification.objects.exists()


@pytest.mark.security
def test_blocking_removes_notifications_between_the_pair(user, other_user, third_user):
    mention(other_user, user)
    mention(user, other_user)
    mention(third_user, user)
    publish("social.block.created", {"blocker_id": user.pk, "blocked_id": other_user.pk}, actor=user)
    assert list(Notification.objects.values_list("actor_id", flat=True)) == [third_user.pk]


def test_reactions_aggregate_and_count_each_actor_once(auth_client, user, other_user, third_user):
    post_id = uuid.uuid4()
    react(user, other_user, post_id)
    react(user, third_user, post_id)
    react(user, other_user, post_id)  # Re-reacting doesn't inflate the count.
    react(user, user, post_id)  # Self.
    items = feed(auth_client(user))
    assert len(items) == 1
    assert items[0]["actor_count"] == 2
    assert items[0]["title"] == "@ngozi and 1 more reacted to your post"
    # Once read, new activity starts a fresh notification.
    auth_client(user).post(f"{BASE}/{items[0]['id']}/read/")
    react(user, create_user("tunde@example.com", handle="tunde"), post_id)
    items = feed(auth_client(user))
    assert len(items) == 2 and items[0]["title"] == "@tunde reacted to your post"


def test_comment_notification_is_skipped_when_a_mention_covers_it(user, other_user):
    comment_id = mention(other_user, user)
    publish(
        "social.comment.created",
        {
            "comment_id": comment_id,
            "post_id": uuid.uuid4(),
            "author_id": other_user.pk,
            "post_author_id": user.pk,
            "parent_id": None,
        },
        actor=other_user,
    )
    assert list(Notification.objects.values_list("verb", flat=True)) == ["social.mention"]
    publish(
        "social.comment.created",
        {
            "comment_id": uuid.uuid4(),
            "post_id": uuid.uuid4(),
            "author_id": other_user.pk,
            "post_author_id": user.pk,
            "parent_id": None,
        },
        actor=other_user,
    )
    assert Notification.objects.filter(verb="social.comment").count() == 1


def test_follows_aggregate_and_requests_are_separate(auth_client, user, other_user, third_user):
    for follower in (other_user, third_user):
        publish("social.follow.created", {"follower_id": follower.pk, "followee_id": user.pk}, actor=follower)
    publish("social.follow.requested", {"follower_id": other_user.pk, "followee_id": user.pk, "follow_id": 1})
    titles = [i["title"] for i in feed(auth_client(user))]
    assert titles == ["@grace requested to follow you", "@ngozi and 1 more started following you"]


@pytest.mark.security
def test_moderation_notices_hide_the_moderator_and_reach_suspended_people(auth_client, user, staff_user, outbox):
    payload = {"action_id": 1, "action": "suspend", "content_type": "users.user", "object_id": str(user.pk)}
    user.status = "suspended"
    user.save()
    publish("moderation.action.taken", {**payload, "target_user_id": user.pk}, actor=staff_user)
    notification = Notification.objects.get()
    assert notification.verb == "moderation.suspend" and notification.actor is None
    assert len(outbox) == 1 and outbox[0].subject == "Your account was suspended by the moderators."
    # Anonymous content carries no target user; dismissals aren't news.
    publish("moderation.action.taken", {**payload, "action": "hide"}, actor=staff_user)
    publish("moderation.action.taken", {**payload, "action": "dismiss", "target_user_id": user.pk})
    assert Notification.objects.count() == 1


def test_appeal_outcomes(auth_client, user, other_user):
    publish("moderation.appeal.decided", {"appeal_id": 1, "outcome": "overturned", "appellant_id": user.pk})
    publish("moderation.appeal.decided", {"appeal_id": 2, "outcome": "upheld"})  # Anonymous: no appellant id.
    assert [i["title"] for i in feed(auth_client(user))] == [
        "Your appeal was successful and the decision was reversed."
    ]


def test_community_events(auth_client, user, other_user, staff_user):
    community = uuid.uuid4()
    publish("community.member.invited", {"community_id": community, "user_id": user.pk, "invited_by": other_user.pk})
    publish("community.member.invited", {"community_id": community, "user_id": user.pk, "invited_by": other_user.pk})
    publish("community.member.joined", {"community_id": community, "user_id": user.pk}, actor=user)  # Self.
    publish("community.member.joined", {"community_id": community, "user_id": user.pk}, actor=staff_user)
    publish("community.role.changed", {"community_id": community, "user_id": user.pk, "role": "moderator"})
    publish("community.role.changed", {"community_id": community, "user_id": user.pk, "role": "admin"})
    titles = [i["title"] for i in feed(auth_client(user))]
    # No community adapter in isolation: the fallback label is used.
    assert titles == [
        "Your role in a community is now admin.",
        "Your role in a community is now moderator.",
        "Your request to join a community was approved.",
        "@grace invited you to join a community",
    ]


def test_security_alerts_are_mandatory_in_app(auth_client, user):
    prefs(user, in_app_enabled=False, categories={"security": {"in_app": False}})
    publish("security.login.suspicious", {"user_id": user.pk, "session_id": 1, "reasons": ["new_device"]}, actor=user)
    items = feed(auth_client(user))
    assert len(items) == 1 and items[0]["category"] == "security" and items[0]["actor"] is None


def test_target_labels_and_availability_respect_the_viewer(auth_client, user, other_user):
    from university.notifications.verbs import Verb, register_verb

    register_verb(
        Verb("test.featured", "communities", "{target} was featured", show_actor=False, target_fallback="An item"),
        replace=True,
    )
    ITEMS["i1"] = {"author": str(other_user.pk), "label": "Campus Hackathon\nmore text"}
    services.notify(recipient=user, verb="test.featured", target_type="test.item", target_id="i1")
    item = feed(auth_client(user))[0]
    assert item["title"] == "Campus Hackathon was featured" and item["target"]["available"] is True
    ITEMS["i1"]["hidden_from"] = {str(user.pk)}
    item = feed(auth_client(user))[0]
    assert item["title"] == "An item was featured" and item["target"]["available"] is False


def test_data_is_limited_to_short_scalars(user, other_user):
    n = services.notify(
        recipient=user,
        verb="social.mention",
        actor=other_user,
        data={"note": "x" * 500, "n": 3, **{f"k{i}": i for i in range(20)}},
    )
    assert len(n.data) == 10 and len(n.data["note"]) == 64 and n.data["n"] == 3


def test_disabled_verbs(settings, user, other_user):
    settings.UNIVERSITY = {"NOTIFICATIONS": {"DISABLED_VERBS": ["social.mention"]}}
    mention(other_user, user)
    assert not Notification.objects.exists()


def test_unknown_verb_is_rendered_generically(auth_client, user, other_user):
    mention(other_user, user)
    Notification.objects.update(verb="removed.module")
    assert feed(auth_client(user))[0]["title"] == "You have a new notification."


# ------------------------------------------------------------ preferences
def test_category_and_channel_preferences(auth_client, user, other_user, third_user):
    prefs(user, categories={"mentions": {"in_app": False}})
    mention(other_user, user)
    hidden = Notification.objects.get()
    assert hidden.in_app is False and feed(auth_client(user)) == []
    # Still delivered by push, the channel left on.
    assert hidden.deliveries.filter(channel="push").exists()
    prefs(user, categories={"mentions": {"in_app": False, "push": False, "email": False}})
    mention(third_user, user)
    assert Notification.objects.count() == 1  # No channel left: nothing created.


def test_categories_endpoint_reports_effective_settings(auth_client, user):
    prefs(user, push_enabled=False, categories={"reactions": {"email": False}})
    data = {c["key"]: c for c in auth_client(user).get(f"{BASE}/categories/").json()}
    assert data["security"]["mandatory"] is True
    assert data["reactions"]["channels"]["email"] == {"default": "digest", "effective": False}
    assert data["mentions"]["channels"]["push"] == {"default": True, "effective": False}
    assert data["mentions"]["channels"]["sms"] == {"default": False, "effective": False}


def test_quiet_hours_respect_the_users_time_zone():
    from types import SimpleNamespace

    from university.notifications.preferences import in_quiet_hours

    lagos = SimpleNamespace(timezone="Africa/Lagos")  # UTC+1
    night = SimpleNamespace(quiet_hours_start=dt.time(22), quiet_hours_end=dt.time(7))
    at = dt.datetime(2026, 5, 1, 22, 30, tzinfo=dt.UTC)  # 23:30 in Lagos
    assert in_quiet_hours(lagos, night, at)
    assert not in_quiet_hours(lagos, night, at.replace(hour=6, minute=30))  # 07:30 in Lagos
    assert in_quiet_hours(SimpleNamespace(timezone="Not/AZone"), night, at)  # Falls back to UTC.
    lunch = SimpleNamespace(quiet_hours_start=dt.time(12), quiet_hours_end=dt.time(13))
    assert in_quiet_hours(lagos, lunch, at.replace(hour=11, minute=15))
    same = SimpleNamespace(quiet_hours_start=dt.time(9), quiet_hours_end=dt.time(9))
    assert not in_quiet_hours(lagos, same, at)


# --------------------------------------------------------------- delivery
def test_immediate_email_contains_no_content_and_needs_a_verified_address(user, outbox):
    publish("moderation.appeal.decided", {"appeal_id": 1, "outcome": "upheld", "appellant_id": user.pk})
    assert len(outbox) == 1
    message = outbox[0]
    assert message.to == [user.email] and "decision stands" in message.subject
    assert message.extra_headers["X-University-Category"] == "moderation"
    assert "/notifications/" in message.body
    unverified = create_user("new@example.com", handle="newbie", verified=False)
    publish("moderation.appeal.decided", {"appeal_id": 2, "outcome": "upheld", "appellant_id": unverified.pk})
    assert len(outbox) == 1
    delivery = Delivery.objects.get(notification__recipient=unverified, channel="email")
    assert (delivery.status, delivery.reason) == (DeliveryStatus.SKIPPED, "unreachable")


def test_push_delivery_quiet_hours_and_invalid_tokens(auth_client, user, other_user):
    assert register(auth_client(user)).status_code == 201
    mention(other_user, user)
    assert len(recording.SENT) == 1
    message = recording.SENT[0]
    assert message.tokens == [TOKEN] and message.title == "@grace mentioned you"
    assert set(message.data) == {"notification_id", "category", "url"}
    # Quiet hours all day: pushes are suppressed, security alerts still go out.
    prefs(user, quiet_hours_start=dt.time(0), quiet_hours_end=dt.time(23, 59, 59))
    mention(create_user("tunde@example.com", handle="tunde"), user)
    assert len(recording.SENT) == 1
    assert Delivery.objects.filter(status=DeliveryStatus.SUPPRESSED, reason="quiet_hours").count() == 1
    publish("security.mfa.disabled", {"user_id": user.pk}, actor=user)
    assert len(recording.SENT) == 2
    # The provider reports the token as unregistered: the device is disabled.
    recording.BEHAVIOUR["mode"] = "invalid"
    publish("user.password_changed", {"user_id": user.pk}, actor=user)
    device = PushDevice.objects.get()
    assert device.disabled_at is not None and device.disabled_reason == "unregistered"


def test_push_previews_can_be_turned_off(settings, auth_client, user, other_user):
    settings.UNIVERSITY = {
        "NOTIFICATIONS": {"PUSH_PROVIDER": "tests.content.push.RecordingPushProvider", "PUSH_PREVIEWS": False}
    }
    register(auth_client(user))
    mention(other_user, user)
    assert recording.SENT[0].title == "You have a new notification"


def test_hourly_push_cap(settings, auth_client, user):
    settings.UNIVERSITY = {
        "NOTIFICATIONS": {"PUSH_PROVIDER": "tests.content.push.RecordingPushProvider", "PUSH_MAX_PER_HOUR": 2}
    }
    register(auth_client(user))
    for i in range(4):
        mention(create_user(f"u{i}@example.com", handle=f"user{i}"), user)
    assert len(recording.SENT) == 2
    assert Delivery.objects.filter(reason="hourly_cap").count() == 2


def test_failed_deliveries_retry_then_fail(settings, auth_client, user, other_user):
    register(auth_client(user))
    recording.BEHAVIOUR["mode"] = "error"
    mention(other_user, user)  # The immediate backend runs each retry at once.
    delivery = Delivery.objects.get(channel="push")
    assert (delivery.status, delivery.attempts, delivery.reason) == (DeliveryStatus.FAILED, 5, "RuntimeError")


def test_a_delivery_is_sent_once(auth_client, user, other_user):
    register(auth_client(user))
    mention(other_user, user)
    delivery = Delivery.objects.get(channel="push")
    deliver(str(delivery.pk))  # A duplicate task message.
    Delivery.objects.filter(pk=delivery.pk).update(status=DeliveryStatus.SENDING)
    deliver(str(delivery.pk))  # Claimed by another worker.
    assert len(recording.SENT) == 1


def test_reading_before_delivery_skips_it(auth_client, user, other_user):
    register(auth_client(user))
    n = services.notify(recipient=user, verb="social.follow_approved", actor=other_user)
    delivery = n.deliveries.get(channel="push")
    assert delivery.status == DeliveryStatus.SENT
    Delivery.objects.filter(pk=delivery.pk).update(status=DeliveryStatus.PENDING)
    services.mark_read(user=user, notification_id=n.pk)
    deliver(str(delivery.pk))
    delivery.refresh_from_db()
    assert (delivery.status, delivery.reason) == (DeliveryStatus.SKIPPED, "already_read")


def test_email_digest(user, other_user, third_user, outbox):
    prefs(user, digest_frequency="daily")
    react(user, other_user, uuid.uuid4())
    react(user, third_user, uuid.uuid4())
    publish("social.follow.created", {"follower_id": other_user.pk, "followee_id": user.pk}, actor=other_user)
    assert outbox == []  # Digest categories don't email immediately.
    assert Delivery.objects.filter(status=DeliveryStatus.DIGEST).count() == 3
    services.mark_read(user=user, notification_id=Notification.objects.get(verb="social.follow").pk)
    assert send_digests("weekly") == 0
    assert send_digests("daily") == 1
    assert len(outbox) == 1
    assert outbox[0].subject == "2 new notifications on University"
    assert "reacted to your post" in outbox[0].body
    assert Delivery.objects.filter(status=DeliveryStatus.SENT, channel="email").count() == 2
    assert Delivery.objects.get(reason="already_read").notification.verb == "social.follow"
    assert send_digests("daily") == 0  # Nothing left.


def test_no_digest_rows_when_digests_are_off(user, other_user):
    prefs(user, digest_frequency="never")
    react(user, other_user, uuid.uuid4())
    assert not Delivery.objects.filter(channel="email").exists()


def test_digest_command(user, other_user, outbox):
    from io import StringIO

    from django.core.management import call_command

    prefs(user, digest_frequency="weekly")
    react(user, other_user, uuid.uuid4())
    out = StringIO()
    call_command("send_notification_digests", "--frequency", "weekly", stdout=out)
    assert "Sent 1 weekly digest" in out.getvalue() and len(outbox) == 1


def test_sms_needs_opt_in_and_a_verified_phone(settings, user):
    from unittest import mock

    prefs(user, sms_enabled=True, categories={"security": {"sms": True}})
    with mock.patch("university.core.providers.sms.ConsoleSMSProvider.send") as send:
        publish("user.password_changed", {"user_id": user.pk}, actor=user)
        assert not send.called  # No verified phone.
        user.phone_number = "+2348031234567"
        user.phone_verified_at = timezone.now()
        user.save()
        publish("user.email_changed", {"user_id": user.pk}, actor=user)
        send.assert_called_once()
        assert send.call_args.args == ("+2348031234567", "University: Your email address was changed.")


# -------------------------------------------------------------- read state
def test_read_unread_seen_and_counts(auth_client, user, other_user, third_user):
    client = auth_client(user)
    mention(other_user, user)
    mention(third_user, user)
    assert client.get(f"{BASE}/counts/").json() == {"unread": 2, "unseen": 2}
    assert client.post(f"{BASE}/seen/").json() == {"updated": 2}
    assert client.get(f"{BASE}/counts/").json() == {"unread": 2, "unseen": 0}
    first = feed(client)[0]
    assert client.post(f"{BASE}/{first['id']}/read/").json()["is_read"] is True
    assert len(feed(client, unread="true")) == 1 and len(feed(client, unread="false")) == 1
    assert client.post(f"{BASE}/{first['id']}/unread/").json()["is_read"] is False
    assert client.post(f"{BASE}/read-all/", {"category": "follows"}, format="json").json() == {"updated": 0}
    past = (timezone.now() - dt.timedelta(days=1)).isoformat()
    assert client.post(f"{BASE}/read-all/", {"before": past}, format="json").json() == {"updated": 0}
    assert client.post(f"{BASE}/read-all/", {}, format="json").json() == {"updated": 2}
    assert client.delete(f"{BASE}/{first['id']}/").status_code == 204
    assert len(feed(client)) == 1


@pytest.mark.security
def test_notifications_are_private_to_their_recipient(auth_client, user, other_user, api_client):
    mention(other_user, user)
    nid = Notification.objects.get().pk
    intruder = auth_client(other_user)
    assert feed(intruder) == []
    for method, path in (("get", ""), ("post", "read/"), ("post", "unread/"), ("delete", "")):
        assert getattr(intruder, method)(f"{BASE}/{nid}/{path}").status_code == 404
    assert api_client.get(f"{BASE}/").status_code == 401


def test_unread_after_new_activity_does_not_collide(user, other_user, third_user):
    post_id = uuid.uuid4()
    react(user, other_user, post_id)
    first = Notification.objects.get()
    services.mark_read(user=user, notification_id=first.pk)
    react(user, third_user, post_id)  # A new unread row in the same group.
    services.mark_unread(user=user, notification_id=first.pk)
    assert Notification.objects.filter(read_at__isnull=True).count() == 2


def test_feed_pagination(auth_client, user):
    for i in range(25):
        mention(create_user(f"p{i}@example.com", handle=f"poster{i}"), user)
    client = auth_client(user)
    first = client.get(f"{BASE}/").json()
    assert len(first["results"]) == 20 and first["next"]
    second = client.get(first["next"]).json()
    assert len(second["results"]) == 5
    ids = {i["id"] for i in first["results"]} | {i["id"] for i in second["results"]}
    assert len(ids) == 25


# ---------------------------------------------------------------- devices
@pytest.mark.security
def test_device_registration(settings, auth_client, user, other_user):
    client = auth_client(user)
    response = register(client)
    assert response.status_code == 201
    body = response.json()
    assert "token" not in body and body["token_suffix"] == TOKEN[-6:] and body["active"] is True
    assert register(client, token="short").status_code == 400
    assert client.post(f"{BASE}/devices/", {"platform": "nokia", "token": TOKEN}, format="json").status_code == 400
    # The same phone signs in to another account: the device moves.
    assert register(auth_client(other_user)).status_code == 201
    assert PushDevice.objects.get().user == other_user
    assert client.get(f"{BASE}/devices/").json() == []
    other = auth_client(other_user)
    device_id = other.get(f"{BASE}/devices/").json()[0]["id"]
    assert client.delete(f"{BASE}/devices/{device_id}/").status_code == 404
    assert other.post(f"{BASE}/devices/unregister/", {"token": TOKEN}, format="json").status_code == 204
    assert not PushDevice.objects.exists()


def test_device_limit_disables_the_oldest(settings, auth_client, user):
    settings.UNIVERSITY = {"NOTIFICATIONS": {"MAX_DEVICES_PER_USER": 2}}
    client = auth_client(user)
    for i in range(3):
        register(client, token=f"token-{i}-" + "y" * 30)
    active = PushDevice.objects.filter(disabled_at__isnull=True)
    assert active.count() == 2 and not active.filter(token__startswith="token-0").exists()


def test_closing_an_account_disables_its_devices(auth_client, user):
    register(auth_client(user))
    publish("user.banned", {"user_id": user.pk})
    assert PushDevice.objects.get().disabled_reason == "account_closed"


# ------------------------------------------------------- privacy lifecycle
def test_export_and_purge(auth_client, user, other_user):
    from university.core.hooks import Hook, hooks

    register(auth_client(user))
    mention(other_user, user)
    mention(user, other_user)
    exported = hooks.collect(Hook.USER_EXPORT_DATA, user)
    assert exported["notification_history"][0]["verb"] == "social.mention"
    assert exported["push_devices"][0]["platform"] == "android" and "token" not in exported["push_devices"][0]
    hooks.call(Hook.USER_PURGE, user.pk)
    assert not Notification.objects.filter(recipient=user).exists()
    assert Notification.objects.get(recipient=other_user).actor is None
    assert not PushDevice.objects.exists()


def test_retention(user, other_user):
    from university.core.retention import run_retention

    mention(other_user, user)
    old = timezone.now() - dt.timedelta(days=400)
    Notification.objects.update(read_at=old, last_activity_at=old)
    Delivery.objects.update(created_at=old)
    results = run_retention(only=["notifications.read", "notifications.deliveries"])
    assert results["notifications.read"] >= 1  # Includes cascaded actor rows.
    assert not Notification.objects.exists()


# --------------------------------------------------------------- providers
def test_fcm_provider(monkeypatch):
    from university.core.exceptions import ProviderError
    from university.notifications import push

    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((url, kwargs))
        if url == push.FCMPushProvider.TOKEN_URI:
            return {"access_token": "ya29.token", "expires_in": 3600}
        token = kwargs["json_body"]["message"]["token"]
        if token == "gone":
            raise ProviderError(code="provider_http_error", details={"status": 404})
        if token == "flaky":
            raise ProviderError(code="provider_http_error", details={"status": 503})
        return {"name": "projects/p/messages/1"}

    monkeypatch.setattr(push, "request", fake_request)
    monkeypatch.setattr("jwt.encode", lambda *a, **k: "signed.jwt")
    provider = push.FCMPushProvider("demo", client_email="svc@demo.iam", private_key="-----KEY-----")
    result = provider.send(push.PushMessage(tokens=["ok", "gone", "flaky"], title="Hi", collapse_key="n1"))
    assert (result.sent, result.invalid_tokens, result.retry) == (1, ["gone"], True)
    sends = [kw for url, kw in calls if url.endswith("messages:send")]
    assert sends[0]["headers"]["Authorization"] == "Bearer ya29.token"
    assert sends[0]["json_body"]["message"]["android"]["collapse_key"] == "n1"
    assert sum(url == push.FCMPushProvider.TOKEN_URI for url, _ in calls) == 1  # Token cached.


def test_expo_provider(monkeypatch):
    from university.notifications import push

    def fake_request(method, url, **kwargs):
        assert url == push.ExpoPushProvider.URL
        return {
            "data": [
                {"status": "ok"},
                {"status": "error", "details": {"error": "DeviceNotRegistered"}},
                {"status": "error", "details": {"error": "MessageRateExceeded"}},
            ]
        }

    monkeypatch.setattr(push, "request", fake_request)
    result = push.ExpoPushProvider().send(push.PushMessage(tokens=["a", "b", "c"], title="Hi"))
    assert (result.sent, result.invalid_tokens, result.retry) == (1, ["b"], True)


@pytest.mark.security
def test_system_notices_never_store_an_actor(user, staff_user):
    n = services.notify(recipient=user, verb="moderation.warn", actor=staff_user)
    assert n.actor is None and not n.actors.exists()
