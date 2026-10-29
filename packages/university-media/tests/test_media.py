from __future__ import annotations

import datetime as dt
import io
import struct
import wave

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from university.core.media import get_media_library, require_media_library
from university.media import services
from university.media.models import AssetStatus, MediaAsset, media_storage

pytestmark = pytest.mark.django_db
BASE = "/api/v1/media"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\xdac\xc8\xd5\xb8\t\x00\x02t\x01o\xfbJ\xd2\xe1\x00\x00\x00\x00IEND\xaeB`\x82"  # A real 1x1 PNG: decodes with or without Pillow.


def wav_bytes(seconds: float = 2.0, rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(struct.pack("<h", 0) * int(seconds * rate))
    return buffer.getvalue()


def upload(client, content=None, name="talk.wav", **data):
    return client.post(
        f"{BASE}/",
        {"file": SimpleUploadedFile(name, content if content is not None else wav_bytes()), **data},
        format="multipart",
    )


def fetch(client, url, **headers):
    response = client.get(url, **headers)
    body = b"".join(response.streaming_content) if hasattr(response, "streaming_content") else response.content
    return response, body


# ------------------------------------------------------------------ uploads
def test_upload_processes_and_streams(auth_client, api_client, user):
    client = auth_client(user)
    created = upload(client)
    assert created.status_code == 201, created.json()
    asset = created.json()
    # The immediate task backend has already processed it.
    detail = client.get(f"{BASE}/{asset['id']}/").json()
    assert detail["status"] == "ready" and detail["kind"] == "audio" and detail["mime_type"] == "audio/wav"
    assert abs(detail["duration_seconds"] - 2.0) < 0.01 and detail["original_name"] == "talk.wav"
    stored = MediaAsset.objects.get(pk=asset["id"])
    assert len(stored.sha256) == 64 and "talk" not in stored.file.name  # Random storage names.
    response, body = fetch(api_client, detail["url"])
    assert response.status_code == 200 and body == wav_bytes()
    assert response["X-Content-Type-Options"] == "nosniff" and response["Accept-Ranges"] == "bytes"
    partial, chunk = fetch(api_client, detail["url"], HTTP_RANGE="bytes=0-99")
    assert partial.status_code == 206 and chunk == wav_bytes()[:100]
    assert partial["Content-Range"] == f"bytes 0-99/{len(wav_bytes())}"
    tail, end = fetch(api_client, detail["url"], HTTP_RANGE="bytes=-10")
    assert tail.status_code == 206 and end == wav_bytes()[-10:]
    assert fetch(api_client, detail["url"], HTTP_RANGE="bytes=999999-")[0].status_code == 416


@pytest.mark.security
def test_signed_links_expire_and_cannot_be_forged(auth_client, api_client, user):
    asset = upload(auth_client(user)).json()
    token = services.signed_token(asset["id"], "original", ttl_seconds=-1)
    assert api_client.get(f"{BASE}/files/{token}/").status_code == 403
    good = services.signed_token(asset["id"], "original")
    assert api_client.get(f"{BASE}/files/{good[:-2]}xx/").status_code == 404


@pytest.mark.security
def test_upload_validation(settings, auth_client, user):
    client = auth_client(user)
    assert upload(client, b"MZ\x90\x00" + b"\x00" * 100, name="song.mp3").status_code == 400  # Executable.
    assert upload(client, b"<html><script>alert(1)</script>", name="x.wav").status_code == 400
    assert upload(client, PNG, name="photo.mp3").status_code == 400  # Extension doesn't match content.
    assert upload(client, PNG, name="pic.png", kind="audio").status_code == 400  # Wrong kind.
    assert upload(client, b"just some text", name="notes.txt").json()["error"]["code"] == "unsupported_media"
    settings.UNIVERSITY = {"MEDIA": {"KINDS": {"audio": {"max_bytes": 100}}}}
    assert upload(client).status_code == 400
    settings.UNIVERSITY = {"MEDIA": {"STORAGE_QUOTA_BYTES_PER_USER": 1000}}
    assert upload(client).json()["error"]["code"] == "quota_exceeded"
    settings.UNIVERSITY = {"MEDIA": {"MAX_PENDING_PER_USER": 0}}
    assert upload(client).json()["error"]["code"] == "too_many_pending"


def test_processing_constraints_fail_the_asset(settings, auth_client, user, captured_events):
    settings.UNIVERSITY = {"MEDIA": {"KINDS": {"audio": {"max_duration_seconds": 1}}}}
    asset = upload(auth_client(user), wav_bytes(3)).json()
    stored = MediaAsset.objects.get(pk=asset["id"])
    assert stored.status == AssetStatus.FAILED and stored.error == "too_long"
    assert "media.asset.failed" in [e.name for e in captured_events]


def test_corrupt_media_fails(auth_client, user):
    asset = upload(auth_client(user), b"RIFF\x00\x00\x00\x00WAVEgarbage" + b"\x00" * 64).json()
    assert MediaAsset.objects.get(pk=asset["id"]).error == "invalid_audio"


@pytest.mark.security
def test_assets_are_private(auth_client, user, other_user):
    asset = upload(auth_client(user)).json()
    other = auth_client(other_user)
    assert other.get(f"{BASE}/{asset['id']}/").status_code == 404
    assert other.delete(f"{BASE}/{asset['id']}/").status_code == 404
    assert (
        other.post(f"{BASE}/{asset['id']}/clips/", {"start_seconds": 0, "end_seconds": 1}, format="json").status_code
        == 404
    )
    assert other.get(f"{BASE}/").json()["count"] == 0


# -------------------------------------------------------------------- clips
def test_clips(auth_client, user):
    client = auth_client(user)
    asset = upload(client, wav_bytes(5)).json()
    url = f"{BASE}/{asset['id']}/clips/"
    assert client.post(url, {"start_seconds": 2, "end_seconds": 1}, format="json").status_code == 400
    assert client.post(url, {"start_seconds": 0, "end_seconds": 9}, format="json").status_code == 400  # Past the end.
    clip = client.post(url, {"start_seconds": 1, "end_seconds": 3}, format="json").json()
    ready = client.get(f"{BASE}/{clip['id']}/").json()
    assert ready["status"] == "ready" and abs(ready["duration_seconds"] - 2.0) < 0.01
    source = MediaAsset.objects.get(pk=asset["id"])
    clip_row = MediaAsset.objects.get(pk=clip["id"])
    assert clip_row.file.name != source.file.name and clip_row.source_id == source.pk
    image = upload(client, PNG, name="pic.png").json()
    unsupported = client.post(f"{BASE}/{image['id']}/clips/", {"start_seconds": 0, "end_seconds": 1}, format="json")
    assert unsupported.json()["error"]["code"] == "clips_unsupported"


def test_deleting_a_failed_clip_keeps_the_source(auth_client, user):
    client = auth_client(user)
    asset = upload(client, wav_bytes(3)).json()
    source = MediaAsset.objects.get(pk=asset["id"])
    clip = MediaAsset.objects.create(
        owner=user,
        kind="audio",
        mime_type="audio/wav",
        source=source,
        clip_start=0,
        clip_end=1,
        status=AssetStatus.FAILED,
        file="",
    )
    client.delete(f"{BASE}/{clip.pk}/")
    assert media_storage().exists(source.file.name)


# ------------------------------------------------------------------ library
@pytest.mark.security
def test_core_media_library(settings, auth_client, user, other_user):
    library = require_media_library()
    assert get_media_library() is library
    asset = upload(auth_client(user)).json()
    from university.core.exceptions import NotFound

    with pytest.raises(NotFound):
        library.attach(asset["id"], owner=other_user, purpose="test.episode", object_id="e1")  # Not theirs.
    ref = library.attach(asset["id"], owner=user, purpose="test.episode", object_id="e1")
    assert ref.is_ready and ref.kind == "audio" and "original" in ref.variants
    assert auth_client(user).delete(f"{BASE}/{asset['id']}/").json()["error"]["code"] == "media_in_use"
    assert library.url(asset["id"]).startswith(f"{BASE}/files/")
    settings.UNIVERSITY = {"MEDIA": {"SERVE_MODE": "storage"}}
    assert library.url(asset["id"]) == MediaAsset.objects.get(pk=asset["id"]).file.url
    library.detach(asset["id"], purpose="test.episode", object_id="e1")
    assert auth_client(user).delete(f"{BASE}/{asset['id']}/").status_code == 204


# ----------------------------------------------------------- direct uploads
def test_direct_uploads(settings, auth_client, user):
    client = auth_client(user)
    assert (
        client.post(f"{BASE}/uploads/", {"kind": "audio", "mime_type": "audio/wav", "size": 10}, format="json").json()[
            "error"
        ]["code"]
        == "direct_uploads_disabled"
    )
    settings.UNIVERSITY = {"MEDIA": {"DIRECT_UPLOADS": {"class": "tests.fakes.StorageDirectUploads"}}}
    content = wav_bytes(1)
    assert (
        client.post(
            f"{BASE}/uploads/", {"kind": "audio", "mime_type": "image/png", "size": 10}, format="json"
        ).status_code
        == 400
    )
    slot = client.post(
        f"{BASE}/uploads/",
        {"kind": "audio", "mime_type": "audio/wav", "size": len(content), "filename": "ep1.wav"},
        format="json",
    ).json()
    assert slot["method"] == "PUT" and slot["url"].startswith("https://storage.test.invalid/media/originals/")
    complete = f"{BASE}/uploads/{slot['upload_id']}/complete/"
    assert client.post(complete).json()["error"]["code"] == "not_uploaded"
    # The client PUTs straight to storage (simulated).
    slot = client.post(
        f"{BASE}/uploads/", {"kind": "audio", "mime_type": "audio/wav", "size": len(content)}, format="json"
    ).json()
    key = slot["url"].split("storage.test.invalid/")[1]
    media_storage().save(key, ContentFile(content))
    asset = client.post(f"{BASE}/uploads/{slot['upload_id']}/complete/").json()
    assert client.get(f"{BASE}/{asset['id']}/").json()["status"] == "ready"
    assert client.post(f"{BASE}/uploads/{slot['upload_id']}/complete/").status_code == 409


@pytest.mark.security
def test_direct_uploads_reject_disguised_files(settings, auth_client, user):
    settings.UNIVERSITY = {"MEDIA": {"DIRECT_UPLOADS": {"class": "tests.fakes.StorageDirectUploads"}}}
    client = auth_client(user)
    payload = b"MZ" + b"\x00" * 98
    slot = client.post(
        f"{BASE}/uploads/", {"kind": "audio", "mime_type": "audio/wav", "size": len(payload)}, format="json"
    ).json()
    key = slot["url"].split("storage.test.invalid/")[1]
    media_storage().save(key, ContentFile(payload))
    rejected = client.post(f"{BASE}/uploads/{slot['upload_id']}/complete/")
    assert rejected.json()["error"]["code"] == "file_type_not_allowed" and not MediaAsset.objects.exists()
    wrong = client.post(
        f"{BASE}/uploads/", {"kind": "audio", "mime_type": "audio/wav", "size": 999}, format="json"
    ).json()
    media_storage().save(wrong["url"].split("storage.test.invalid/")[1], ContentFile(wav_bytes(1)))
    assert client.post(f"{BASE}/uploads/{wrong['upload_id']}/complete/").json()["error"]["code"] == "size_mismatch"


# ---------------------------------------------------------------- ffmpeg
@pytest.mark.security
def test_ffmpeg_processor_is_sandboxed(monkeypatch, tmp_path):
    import json
    import subprocess

    from university.media import processing

    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        out = b""
        if args[0] == "ffprobe":
            out = json.dumps(
                {
                    "format": {"duration": "61.5"},
                    "streams": [{"codec_type": "video", "width": 1920, "height": 1080}, {"codec_type": "audio"}],
                }
            ).encode()
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr=b"")

    monkeypatch.setattr(processing.subprocess, "run", fake_run)
    result = processing.FFmpegProcessor().process(
        kind="video", mime_type="video/mp4", source="in.mp4", workdir=str(tmp_path)
    )
    assert (result.duration_seconds, result.width, result.height) == (61.5, 1920, 1080)
    assert [name for name, _, _ in result.variants] == ["mp3", "mp4_720p", "poster"]
    for args, kwargs in calls:
        assert isinstance(args, list) and "shell" not in kwargs and kwargs["timeout"]
        assert "-protocol_whitelist" in args and args[args.index("-protocol_whitelist") + 1] == "file"
    monkeypatch.setattr(processing.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 1, b"", b""))
    with pytest.raises(processing.ProcessingError):
        processing.FFmpegProcessor().probe("in.mp4")


# ---------------------------------------------------------- privacy, misc
def test_retention_export_and_purge(auth_client, user):
    from university.core.hooks import Hook, hooks
    from university.core.retention import run_retention

    client = auth_client(user)
    orphan = upload(client).json()
    kept = upload(client).json()
    require_media_library().attach(kept["id"], owner=user, purpose="test.episode", object_id="e1")
    MediaAsset.objects.update(created_at=timezone.now() - dt.timedelta(days=3))
    orphan_file = MediaAsset.objects.get(pk=orphan["id"]).file.name
    assert run_retention(only=["media.orphans"])["media.orphans"] == 1
    assert not media_storage().exists(orphan_file) and MediaAsset.objects.filter(pk=kept["id"]).exists()
    assert hooks.collect(Hook.USER_EXPORT_DATA, user)["media"][0]["name"] == "talk.wav"
    kept_file = MediaAsset.objects.get(pk=kept["id"]).file.name
    hooks.call(Hook.USER_PURGE, user.pk)
    assert not MediaAsset.objects.exists() and not media_storage().exists(kept_file)


@pytest.fixture
def captured_events():
    from university.core.events import event_bus

    seen: list = []
    event_bus.subscribe("media.*", seen.append)
    yield seen
    event_bus.unsubscribe("media.*", seen.append)
