"""Profile photos.

Uploads are validated by their real content (magic bytes, not the file name), then decoded and
re-encoded with Pillow: orientation is applied, the image is cropped square and resized, and
**all metadata is dropped**, so a photo can't leak where or when it was taken (EXIF/GPS). Only the
re-encoded WebP is stored, under a random name.
"""

from __future__ import annotations

import io
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.base import ContentFile
from django.db import transaction

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.conf import university_settings
from university.core.events import publish
from university.core.exceptions import ServiceUnavailable, ValidationError
from university.core.uploads import FileUploadValidator
from university.users import events


def _config(name: str) -> Any:
    return university_settings.get(f"USERS.AVATAR.{name}")


def _reencode(file: Any) -> ContentFile:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ServiceUnavailable(
            "Profile photos need image support on the server (pip install 'university-core[images]').",
            code="images_unavailable",
        ) from None
    size = int(_config("SIZE"))
    try:
        file.seek(0)
        with Image.open(file) as source:
            image = ImageOps.exif_transpose(source)
            image = image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
            image = ImageOps.fit(image, (size, size), method=Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="WEBP", quality=int(_config("QUALITY")), method=4)  # No EXIF written.
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError(details={"file": ["The image is corrupt or unsupported."]}) from exc
    return ContentFile(buffer.getvalue(), name="avatar.webp")


@transaction.atomic
def set_avatar(user: Any, file: Any) -> Any:
    validator = FileUploadValidator(allowed_mime_types=_config("MIME_TYPES"), max_bytes=int(_config("MAX_BYTES")))
    try:
        validator(file)
    except DjangoValidationError as exc:
        raise ValidationError(details={"file": exc.messages}) from None
    content = _reencode(file)
    old = user.avatar.name if user.avatar else None
    user._upload_file = content  # uuid_upload_to derives the extension from the content.
    user.avatar.save(content.name, content, save=False)
    user.save(update_fields=["avatar", "updated_at"])
    if old:
        storage = user.avatar.storage
        transaction.on_commit(lambda: storage.delete(old))
    audit(AuditAction.PROFILE_PHOTO_CHANGED, actor=user, target=user)
    publish(events.USER_UPDATED, {"user_id": user.pk, "fields": ["avatar"]}, actor=user)
    return user


@transaction.atomic
def remove_avatar(user: Any) -> Any:
    if user.avatar:
        user.avatar.delete(save=False)
        user.save(update_fields=["avatar", "updated_at"])
        audit(AuditAction.PROFILE_PHOTO_REMOVED, actor=user, target=user)
        publish(events.USER_UPDATED, {"user_id": user.pk, "fields": ["avatar"]}, actor=user)
    return user


def avatar_url(user: Any) -> str | None:
    """The public URL of someone's profile photo, or None (deleted accounts never have one)."""
    avatar = getattr(user, "avatar", None)
    if not avatar or getattr(user, "anonymized_at", None):
        return None
    try:
        return avatar.url
    except ValueError:
        return None
