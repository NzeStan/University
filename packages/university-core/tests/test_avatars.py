import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from university.core.api.schema import paginated
from university.users.refs import PersonRefSerializer, person_ref

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

pytestmark = pytest.mark.django_db
AVATAR = "/api/v1/me/avatar/"


def photo(size=(1200, 800), fmt="JPEG", gps=True, name="me.jpg"):
    image = Image.new("RGB", size, (200, 30, 90))
    buffer = io.BytesIO()
    kwargs = {}
    if gps and fmt == "JPEG":
        exif = Image.Exif()
        exif[0x010F] = "PhoneMaker"  # Make
        exif[0x8825] = {1: "N", 2: (6.0, 31.0, 0.0), 3: "E", 4: (3.0, 22.0, 0.0)}  # GPSInfo: Lagos
        kwargs["exif"] = exif.tobytes()
    image.save(buffer, format=fmt, **kwargs)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


@pytest.mark.security
def test_upload_strips_metadata_and_crops_square(auth_client, user, settings, tmp_path):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": tmp_path}},
    }
    original = photo()
    assert b"Exif" in original.read()
    original.seek(0)
    response = auth_client(user).post(AVATAR, {"file": original}, format="multipart")
    assert response.status_code == 200, response.content
    assert response.json()["avatar_url"]
    user.refresh_from_db()
    assert user.avatar.name.endswith(".webp") and "me.jpg" not in user.avatar.name
    with user.avatar.open("rb") as stored:
        data = stored.read()
    with Image.open(io.BytesIO(data)) as saved:
        assert saved.format == "WEBP" and saved.size == (512, 512)
        assert not saved.getexif()  # No GPS, no camera make: nothing.
    assert b"PhoneMaker" not in data
    # Public profile and the shared person shape carry the photo.
    public = auth_client(user).get(f"/api/v1/users/{user.pk}/").json()
    assert public["avatar_url"] == response.json()["avatar_url"]
    assert person_ref(user)["avatar_url"] == public["avatar_url"]


def test_replacing_deletes_the_old_file_and_removal_works(auth_client, user, settings, tmp_path):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": tmp_path}},
    }
    client = auth_client(user)
    client.post(AVATAR, {"file": photo()}, format="multipart")
    user.refresh_from_db()
    first = user.avatar.name
    client.post(AVATAR, {"file": photo(fmt="PNG", gps=False, name="new.png")}, format="multipart")
    user.refresh_from_db()
    assert user.avatar.name != first and not user.avatar.storage.exists(first)
    assert client.delete(AVATAR).json()["avatar_url"] is None
    user.refresh_from_db()
    assert not user.avatar


@pytest.mark.security
@pytest.mark.parametrize(
    "upload",
    [
        SimpleUploadedFile("evil.jpg", b"<html><script>alert(1)</script></html>", content_type="image/jpeg"),
        SimpleUploadedFile("doc.pdf", b"%PDF-1.7 not an image", content_type="image/jpeg"),
    ],
)
def test_rejects_files_that_are_not_images(auth_client, user, upload):
    response = auth_client(user).post(AVATAR, {"file": upload}, format="multipart")
    assert response.status_code == 400 and "file" in response.json()["error"]["details"]


def test_rejects_oversized_uploads(auth_client, user, settings):
    settings.UNIVERSITY = {"USERS": {"AVATAR": {"MAX_BYTES": 1000}}}
    response = auth_client(user).post(AVATAR, {"file": photo()}, format="multipart")
    assert response.status_code == 400


def test_purge_deletes_the_photo(auth_client, user, settings, tmp_path):
    from university.users.services import delete_account, purge_user

    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": tmp_path}},
    }
    auth_client(user).post(AVATAR, {"file": photo()}, format="multipart")
    user.refresh_from_db()
    name = user.avatar.name
    delete_account(user, password="Correct-Horse-Battery-9")
    purge_user(user)
    assert not user.avatar and not user.avatar.storage.exists(name)
    assert person_ref(user)["avatar_url"] is None


def test_person_ref_shape(user):
    assert set(person_ref(user)) == {"id", "handle", "display_name", "avatar_url"}
    assert PersonRefSerializer(user).data["id"] == str(user.pk)
    assert person_ref(None) is None


def test_paginated_schema_helper():
    page = paginated(PersonRefSerializer)
    cursor = paginated(PersonRefSerializer, style="cursor")
    assert page.__name__ == "PaginatedPersonRefListSerializer" and "count" in page().fields
    assert "count" not in cursor().fields and "next" in cursor().fields
    assert paginated(PersonRefSerializer) is page  # Cached: one component per item and style.
    with pytest.raises(ValueError):
        paginated(PersonRefSerializer, style="weird")
