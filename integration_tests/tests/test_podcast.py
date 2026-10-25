"""Podcast and media composed with community, social, notifications and moderation."""

from __future__ import annotations

import io
import struct
import wave

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from university.community import services as community_services
from university.core.testing import create_user
from university.media.models import MediaAsset
from university.moderation.models import ModerationCase

pytestmark = pytest.mark.django_db
POD = "/api/v1/podcasts"


def wav(seconds: float = 3.0) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<h", 0) * int(seconds * 8000))
    return buffer.getvalue()


def titles(client):
    return [n["title"] for n in client.get("/api/v1/notifications/").json()["results"]]


def upload(client):
    response = client.post("/api/v1/media/", {"file": SimpleUploadedFile("ep.wav", wav())}, format="multipart")
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def community_show(client, club):
    show = client.post(
        f"{POD}/",
        {"title": "Robotics Radio", "category": "Technology", "host_type": "community", "host_id": str(club.pk)},
        format="json",
    )
    assert show.status_code == 201, show.json()
    show = show.json()
    client.post(f"{POD}/{show['id']}/status/", {"action": "publish"}, format="json")
    return show


@pytest.fixture
def club(user):
    return community_services.create_community(creator=user, data={"name": "Robotics"})


def test_community_hosted_podcast_and_subscriber_notifications(auth_client, user, other_user, club):
    owner = auth_client(user)
    show = community_show(owner, club)  # Community owners hold podcast.manage at their community.
    listener = auth_client(other_user)
    listener.post(f"{POD}/{show['id']}/subscription/")
    episode = owner.post(
        f"{POD}/{show['id']}/episodes/", {"title": "Episode 1", "audio_media_id": upload(owner)}, format="json"
    ).json()
    owner.post(f"{POD}/episodes/{episode['id']}/publish/", {}, format="json")
    assert titles(listener) == ["New episode of Robotics Radio."]


@pytest.mark.security
def test_episode_reports_go_to_the_host_communitys_moderators(auth_client, user, other_user, club):
    owner = auth_client(user)
    show = community_show(owner, club)
    episode = owner.post(
        f"{POD}/{show['id']}/episodes/", {"title": "Hot take", "audio_media_id": upload(owner)}, format="json"
    ).json()
    owner.post(f"{POD}/episodes/{episode['id']}/publish/", {}, format="json")
    reporter = create_user("ngozi@example.com", handle="ngozi")
    report = auth_client(reporter).post(
        "/api/v1/moderation/reports/",
        {"content_type": "podcast.episode", "object_id": episode["id"], "reason": "harassment"},
        format="json",
    )
    assert report.status_code == 201, report.json()
    case = ModerationCase.objects.get()
    assert (case.scope_type, case.scope_id) == ("community", str(club.pk))


@pytest.mark.security
def test_blocked_users_cannot_be_added_as_guests(auth_client, user, other_user, club):
    owner = auth_client(user)
    show = community_show(owner, club)
    episode = owner.post(f"{POD}/{show['id']}/episodes/", {"title": "Ep"}, format="json").json()
    auth_client(other_user).post(f"/api/v1/social/users/{user.pk}/block/")
    blocked = owner.post(
        f"{POD}/episodes/{episode['id']}/guests/", {"name": "Grace", "user_id": str(other_user.pk)}, format="json"
    )
    assert blocked.status_code == 404
    added = owner.post(f"{POD}/episodes/{episode['id']}/guests/", {"name": "Grace (unlinked)"}, format="json")
    assert added.status_code == 201


def test_guest_invitation_notification(auth_client, user, other_user, club):
    owner = auth_client(user)
    show = community_show(owner, club)
    episode = owner.post(f"{POD}/{show['id']}/episodes/", {"title": "Ep"}, format="json").json()
    owner.post(
        f"{POD}/episodes/{episode['id']}/guests/", {"name": "Grace", "user_id": str(other_user.pk)}, format="json"
    )
    assert titles(auth_client(other_user)) == [
        "You were added as a guest on Robotics Radio. Confirm to appear on your profile."
    ]


def test_failed_uploads_notify_the_uploader(settings, auth_client, user):
    settings.UNIVERSITY = {"MEDIA": {"KINDS": {"audio": {"max_duration_seconds": 1}}}}
    auth_client(user).post("/api/v1/media/", {"file": SimpleUploadedFile("long.wav", wav(5))}, format="multipart")
    assert MediaAsset.objects.get().error == "too_long"
    assert titles(auth_client(user)) == ["Your upload couldn't be processed."]


def test_media_library_is_shared_through_core():
    from university.core.media import get_media_library
    from university.media.library import Library

    assert isinstance(get_media_library(), Library)
