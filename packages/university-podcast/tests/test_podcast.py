from __future__ import annotations

import datetime as dt
import io
import struct
import wave

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from tests import fakes
from tests.audience.apps import MEMBERS
from university.core.events import event_bus
from university.permissions.scopes import Scope
from university.permissions.services import assign_role
from university.podcast import services
from university.podcast.models import Episode, EpisodeDailyStat, Podcast

pytestmark = pytest.mark.django_db
BASE = "/api/v1/podcasts"
INST = "11111111-1111-4111-8111-111111111111"
VTT = """WEBVTT

1
00:00:00.000 --> 00:00:02.500
<v Ada>Welcome to <b>Campus Talk</b>!</v>

2
00:00:02.500 --> 00:00:05.000
Today: exams &amp; sleep.
"""


def wav(seconds: float = 4.0) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<h", 0) * int(seconds * 8000))
    return buffer.getvalue()


def upload(client, content=None, name="ep.wav"):
    response = client.post("/api/v1/media/", {"file": SimpleUploadedFile(name, content or wav())}, format="multipart")
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def show(client, **data):
    response = client.post(
        f"{BASE}/",
        {"title": "Campus Talk", "description": "Student life", "category": "Education", **data},
        format="json",
    )
    assert response.status_code == 201, response.json()
    return response.json()


def episode(client, podcast, media_id=None, **data):
    payload = {"title": "Exams and sleep", "summary": "How to survive", **data}
    if media_id:
        payload["audio_media_id"] = media_id
    response = client.post(f"{BASE}/{podcast['id']}/episodes/", payload, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def live(client, **show_data):
    podcast = show(client, **show_data)
    client.post(f"{BASE}/{podcast['id']}/status/", {"action": "publish"}, format="json")
    ep = episode(client, podcast, upload(client))
    assert client.post(f"{BASE}/episodes/{ep['id']}/publish/", {}, format="json").status_code == 200
    return podcast, ep


@pytest.fixture
def captured():
    seen: list = []
    event_bus.subscribe("podcast.*", seen.append)
    yield seen
    event_bus.unsubscribe("podcast.*", seen.append)


# -------------------------------------------------------------- shows, eps
def test_show_and_episode_lifecycle(auth_client, api_client, user, captured):
    host = auth_client(user)
    podcast = show(host)
    assert podcast["viewer"]["role"] == "owner" and podcast["author_name"] == "ada"
    assert api_client.get(f"{BASE}/{podcast['id']}/").status_code == 404  # Draft.
    host.post(f"{BASE}/{podcast['id']}/status/", {"action": "publish"}, format="json")
    draft = episode(host, podcast)
    assert (
        host.post(f"{BASE}/episodes/{draft['id']}/publish/", {}, format="json").json()["error"]["code"]
        == "media_required"
    )
    host.patch(f"{BASE}/episodes/{draft['id']}/", {"audio_media_id": upload(host)}, format="json")
    published = host.post(f"{BASE}/episodes/{draft['id']}/publish/", {}, format="json").json()
    assert published["status"] == "published" and abs(published["duration_seconds"] - 4.0) < 0.01
    assert [e["title"] for e in api_client.get(f"{BASE}/{podcast['id']}/episodes/").json()["results"]] == [
        "Exams and sleep"
    ]
    assert api_client.get(f"{BASE}/by-slug/{podcast['slug']}/").json()["id"] == podcast["id"]
    assert "podcast.episode.published" in [e.name for e in captured]
    host.post(f"{BASE}/episodes/{draft['id']}/unpublish/")
    assert api_client.get(f"{BASE}/episodes/{draft['id']}/").status_code == 404


def test_validation(auth_client, user):
    host = auth_client(user)
    base = {"title": "x"}
    assert host.post(f"{BASE}/", {**base, "category": "Nope"}, format="json").status_code == 400
    assert host.post(f"{BASE}/", {**base, "language": "zz"}, format="json").status_code == 400
    assert host.post(f"{BASE}/", {**base, "website": "http://insecure.example"}, format="json").status_code == 400
    assert host.post(f"{BASE}/", {**base, "visibility": "audience"}, format="json").status_code == 400


@pytest.mark.security
def test_media_must_belong_to_the_editor(auth_client, user, other_user):
    host = auth_client(user)
    podcast = show(host)
    host.post(f"{BASE}/{podcast['id']}/members/", {"user_id": str(other_user.pk), "role": "host"}, format="json")
    stolen = upload(auth_client(other_user))
    # Grace (a host) can attach her own media, but nobody can attach someone else's.
    third = episode(auth_client(other_user), podcast, stolen)
    assert third["has_audio"] is True
    mine = upload(host)
    assert (
        auth_client(other_user)
        .patch(f"{BASE}/episodes/{third['id']}/", {"audio_media_id": mine}, format="json")
        .status_code
        == 404
    )
    image = upload(
        host,
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\xdac\xc8\xd5\xb8\t\x00\x02t\x01o\xfbJ\xd2\xe1\x00\x00\x00\x00IEND\xaeB`\x82",
        name="cover.png",
    )
    wrong = host.post(f"{BASE}/{podcast['id']}/episodes/", {"title": "x", "audio_media_id": image}, format="json")
    assert wrong.json()["error"]["code"] == "wrong_media_kind"


@pytest.mark.security
def test_members_ranks_and_audience_shows(auth_client, api_client, user, other_user, third_user):
    host = auth_client(user)
    podcast = show(host)
    url = f"{BASE}/{podcast['id']}/members/"
    host.post(url, {"user_id": str(other_user.pk), "role": "producer"}, format="json")
    producer = auth_client(other_user)
    assert producer.post(url, {"user_id": str(third_user.pk), "role": "producer"}, format="json").status_code == 403
    assert producer.delete(f"{url}{user.pk}/").json()["error"]["code"] == "owner_must_transfer"
    assert (
        auth_client(third_user).post(f"{BASE}/{podcast['id']}/episodes/", {"title": "x"}, format="json").status_code
        == 404
    )  # Draft show.
    payload = {
        "title": "EXU Radio",
        "category": "News",
        "visibility": "audience",
        "host_type": "institution",
        "host_id": INST,
    }
    assert host.post(f"{BASE}/", payload, format="json").status_code == 403
    assign_role(user=user, role_key="podcast_manager", scope=Scope("institution", INST))
    radio = host.post(f"{BASE}/", payload, format="json").json()
    host.post(f"{BASE}/{radio['id']}/status/", {"action": "publish"}, format="json")
    assert api_client.get(f"{BASE}/{radio['id']}/").status_code == 404
    MEMBERS[str(third_user.pk)] = [("institution", INST)]
    assert auth_client(third_user).get(f"{BASE}/").json()["count"] == 1
    assert (
        api_client.get(f"{BASE}/{radio['slug']}/feed.xml").status_code == 404
    )  # No public feed for members-only shows.


# ------------------------------------------------------- streaming & stats
def test_stream_redirects_to_signed_media(auth_client, api_client, user):
    podcast, ep = live(auth_client(user))
    response = api_client.get(f"{BASE}/episodes/{ep['id']}/stream/")
    assert response.status_code == 302 and response["Location"].startswith("/api/v1/media/files/")
    assert response["Cache-Control"] == "private, no-store"
    media = api_client.get(response["Location"])
    assert media.status_code == 200 and b"".join(media.streaming_content).startswith(b"RIFF")


def test_plays_are_aggregated_and_deduplicated(auth_client, api_client, user, other_user):
    podcast, ep = live(auth_client(user))
    listener = auth_client(other_user)
    assert listener.post(f"{BASE}/episodes/{ep['id']}/plays/", {"position_seconds": 1}, format="json").json() == {
        "play": True,
        "completion": False,
    }
    assert listener.post(f"{BASE}/episodes/{ep['id']}/plays/", {"position_seconds": 3.9}, format="json").json() == {
        "play": False,
        "completion": True,
    }
    assert listener.post(f"{BASE}/episodes/{ep['id']}/plays/", {"position_seconds": 4}, format="json").json() == {
        "play": False,
        "completion": False,
    }
    api_client.post(f"{BASE}/episodes/{ep['id']}/plays/", {"position_seconds": 0}, format="json")
    stat = EpisodeDailyStat.objects.get()
    assert (stat.plays, stat.completions) == (2, 1)
    report = auth_client(user).get(f"{BASE}/{podcast['id']}/analytics/").json()
    assert report["episodes"][0]["plays"] == 2
    assert listener.get(f"{BASE}/{podcast['id']}/analytics/").status_code == 403


def test_rss_feed(auth_client, api_client, user):
    host = auth_client(user)
    podcast, ep = live(host, description="Tips & tricks <for> students")
    host.put(f"{BASE}/episodes/{ep['id']}/transcript/", {"content": VTT, "format": "vtt"}, format="json")
    feed = api_client.get(f"{BASE}/{podcast['slug']}/feed.xml")
    assert feed["Content-Type"].startswith("application/rss+xml")
    body = feed.content.decode()
    import xml.etree.ElementTree as ET

    root = ET.fromstring(body)  # noqa: S314 - our own feed. Well-formed despite & and < in the description.
    item = root.find("channel/item")
    assert item.find("title").text == "Exams and sleep"
    enclosure = item.find("enclosure")
    assert (
        enclosure.get("url").endswith(f"/api/v1/podcasts/episodes/{ep['id']}/stream/")
        and enclosure.get("type") == "audio/wav"
    )
    assert "itunes:duration" in body and "00:00:04" in body and "podcast:transcript" in body
    assert api_client.get(f"{BASE}/not-a-show/feed.xml").status_code == 404


# ------------------------------------------------------------ transcripts
def test_transcripts(settings, auth_client, api_client, user):
    host = auth_client(user)
    podcast, ep = live(host)
    url = f"{BASE}/episodes/{ep['id']}/transcript/"
    assert api_client.get(url).status_code == 404
    assert (
        host.put(
            url, {"content": "WEBVTT\n\n00:00:05.000 --> 00:00:01.000\nBackwards", "format": "vtt"}, format="json"
        ).status_code
        == 400
    )
    saved = host.put(url, {"content": VTT, "format": "vtt"}, format="json").json()
    assert [c["text"] for c in saved["cues"]] == [
        "Welcome to Campus Talk!",
        "Today: exams & sleep.",
    ]  # Markup stripped.
    srt = "1\n00:00:01,000 --> 00:00:02,000\nHello\n"
    assert host.put(url, {"content": srt, "format": "srt"}, format="json").json()["cues"][0]["start"] == 1.0
    host.put(url, {"content": VTT, "format": "vtt"}, format="json")
    vtt = api_client.get(f"{BASE}/episodes/{ep['id']}/transcript.vtt").content.decode()
    assert vtt.startswith("WEBVTT") and "00:00:02.500 --> 00:00:05.000" in vtt
    assert api_client.get(url).json()["text"].startswith("Welcome")
    assert host.put(url, {"content": "x" * 10, "format": "text"}, format="json").json()["cues"] == []
    settings.UNIVERSITY = {"PODCAST": {"TRANSCRIPT_MAX_BYTES": 10}}
    assert host.put(url, {"content": VTT, "format": "vtt"}, format="json").status_code == 400


def test_automatic_transcription(settings, auth_client, user):
    host = auth_client(user)
    podcast, ep = live(host)
    url = f"{BASE}/episodes/{ep['id']}/transcript/generate/"
    assert host.post(url, {}, format="json").json()["error"]["code"] == "transcription_unavailable"
    settings.UNIVERSITY = {"PODCAST": {"TRANSCRIPTION_PROVIDER": "tests.fakes.FakeTranscriber"}}
    fakes.CALLS.clear()
    assert host.post(url, {"language": "en"}, format="json").status_code == 202
    transcript = host.get(f"{BASE}/episodes/{ep['id']}/transcript/").json()
    assert transcript["status"] == "ready" and transcript["automatic"] is True
    assert transcript["cues"] == [{"start": 0.0, "end": 1.5, "text": "Welcome to the show."}]  # Blank cues dropped.
    assert fakes.CALLS[0]["audio_url"].startswith("/api/v1/media/files/")


# ------------------------------------------------------------ clips, guests
def test_clips(auth_client, api_client, user, other_user):
    host = auth_client(user)
    podcast, ep = live(host)
    clip = host.post(
        f"{BASE}/episodes/{ep['id']}/clips/",
        {"title": "Best bit", "start_seconds": 1, "end_seconds": 2.5},
        format="json",
    )
    assert clip.status_code == 201, clip.json()
    assert [c["title"] for c in api_client.get(f"{BASE}/episodes/{ep['id']}/clips/").json()] == ["Best bit"]
    assert api_client.get(f"{BASE}/clips/{clip.json()['id']}/stream/").status_code == 302
    assert (
        auth_client(other_user)
        .post(f"{BASE}/episodes/{ep['id']}/clips/", {"title": "x", "start_seconds": 0, "end_seconds": 1}, format="json")
        .status_code
        == 403
    )
    assert (
        host.post(
            f"{BASE}/episodes/{ep['id']}/clips/", {"title": "x", "start_seconds": 0, "end_seconds": 500}, format="json"
        ).status_code
        == 400
    )
    assert host.delete(f"{BASE}/clips/{clip.json()['id']}/").status_code == 204


@pytest.mark.security
def test_guests_are_linked_only_after_consent(auth_client, api_client, user, other_user):
    host = auth_client(user)
    podcast, ep = live(host)
    guest = host.post(
        f"{BASE}/episodes/{ep['id']}/guests/",
        {"name": "Dr. Grace", "bio": "Sleep scientist", "user_id": str(other_user.pk)},
        format="json",
    ).json()
    assert guest["user"] is None  # Not confirmed yet.
    assert api_client.get(f"{BASE}/episodes/{ep['id']}/").json()["guests"][0]["user"] is None
    auth_client(other_user).post(f"{BASE}/guest-spots/{guest['id']}/respond/", {"accept": True}, format="json")
    linked = api_client.get(f"{BASE}/episodes/{ep['id']}/").json()["guests"][0]["user"]
    assert linked["handle"] == "grace"
    auth_client(other_user).post(f"{BASE}/guest-spots/{guest['id']}/respond/", {"accept": False}, format="json")
    assert api_client.get(f"{BASE}/episodes/{ep['id']}/").json()["guests"][0]["user"] is None


# ---------------------------------------------- subscriptions & scheduling
def test_subscriptions_and_scheduled_publishing(auth_client, user, other_user, captured):
    host = auth_client(user)
    podcast = show(host)
    host.post(f"{BASE}/{podcast['id']}/status/", {"action": "publish"}, format="json")
    listener = auth_client(other_user)
    listener.post(f"{BASE}/{podcast['id']}/subscription/")
    listener.post(f"{BASE}/{podcast['id']}/subscription/")  # Idempotent.
    assert Podcast.objects.get(pk=podcast["id"]).subscriber_count == 1
    ep = episode(host, podcast, upload(host))
    later = (timezone.now() + dt.timedelta(hours=1)).isoformat()
    assert (
        host.post(f"{BASE}/episodes/{ep['id']}/publish/", {"publish_at": later}, format="json").json()["status"]
        == "scheduled"
    )
    assert listener.get(f"{BASE}/episodes/{ep['id']}/").status_code == 404
    assert services.publish_due_episodes() == 0
    Episode.objects.filter(pk=ep["id"]).update(publish_at=timezone.now() - dt.timedelta(minutes=1))
    assert services.publish_due_episodes() == 1
    notices = [e.payload for e in captured if e.name == "podcast.subscriber.notice"]
    assert notices == [{"user_id": str(other_user.pk), "episode_id": ep["id"], "podcast_id": podcast["id"]}]
    assert listener.get("/api/v1/me/podcast-subscriptions/").json()["count"] == 1
    listener.delete(f"{BASE}/{podcast['id']}/subscription/")
    assert Podcast.objects.get(pk=podcast["id"]).subscriber_count == 0


# -------------------------------------------------------------- moderation
@pytest.mark.security
def test_moderation_adapters(auth_client, api_client, user):
    from university.core.content import get_moderatable_adapter
    from university.media.models import MediaAttachment

    host = auth_client(user)
    podcast, ep = live(host)
    adapter = get_moderatable_adapter("podcast.episode")
    assert adapter.resolve(ep["id"]).author_id == str(user.pk)
    adapter.hide(ep["id"], reason="Hate speech")
    assert api_client.get(f"{BASE}/episodes/{ep['id']}/").status_code == 404
    assert api_client.get(f"{BASE}/episodes/{ep['id']}/stream/").status_code == 404
    assert (
        host.post(f"{BASE}/episodes/{ep['id']}/publish/", {}, format="json").json()["error"]["code"] == "episode_hidden"
    )
    adapter.remove(ep["id"], reason="Hate speech")
    assert not MediaAttachment.objects.exists()  # The media is released (and later cleaned up as an orphan).
    get_moderatable_adapter("podcast.show").hide(podcast["id"], reason="Spam")
    assert api_client.get(f"{BASE}/{podcast['id']}/").status_code == 404


def test_export_purge_and_retention(auth_client, user, other_user):
    from university.core.hooks import Hook, hooks
    from university.core.retention import run_retention

    host = auth_client(user)
    podcast, ep = live(host)
    host.post(f"{BASE}/{podcast['id']}/members/", {"user_id": str(other_user.pk), "role": "host"}, format="json")
    auth_client(other_user).post(f"{BASE}/{podcast['id']}/subscription/")
    assert hooks.collect(Hook.USER_EXPORT_DATA, user)["podcast_memberships"][0]["role"] == "owner"
    hooks.call(Hook.USER_PURGE, user.pk)
    refreshed = Podcast.objects.get(pk=podcast["id"])
    assert refreshed.owner_id == other_user.pk and refreshed.members.get(user=other_user).role == "owner"
    hooks.call(Hook.USER_PURGE, other_user.pk)
    assert Podcast.objects.get(pk=podcast["id"]).status == "archived"
    EpisodeDailyStat.objects.create(episode_id=ep["id"], date=timezone.localdate() - dt.timedelta(days=800), plays=1)
    assert run_retention(only=["podcast.listening_stats"])["podcast.listening_stats"] == 1


def test_episodes_wait_for_media_processing(auth_client, user):
    from university.media.models import MediaAsset

    host = auth_client(user)
    podcast = show(host)
    media_id = upload(host)
    MediaAsset.objects.filter(pk=media_id).update(status="processing")  # A worker hasn't finished yet.
    ep = episode(host, podcast, media_id)
    blocked = host.post(f"{BASE}/episodes/{ep['id']}/publish/", {}, format="json")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "media_not_ready"
