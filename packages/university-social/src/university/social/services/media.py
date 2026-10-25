"""Image uploads for posts.

Uploads are validated by content signature (never the client's
``Content-Type``), stored under random names, and owned by the uploader until
attached to one of *their* posts. Unattached uploads are purged by a
retention policy. For audience-restricted posts, configure the default
storage to serve signed, expiring URLs (e.g. S3 ``querystring_auth``).
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from university.core.exceptions import NotFound, ValidationError
from university.core.ratelimit import rate_limit
from university.core.uploads import FileUploadValidator
from university.social.conf import social_settings
from university.social.models import PostMedia


def _dimensions(file: Any) -> tuple[int | None, int | None]:
    try:
        from PIL import Image
    except ImportError:
        return None, None
    try:
        file.seek(0)
        with Image.open(file) as image:
            return image.size
    except Exception:
        return None, None
    finally:
        file.seek(0)


@transaction.atomic
def upload_media(*, owner: Any, file: Any, alt_text: str = "") -> PostMedia:
    rate_limit("social_media_upload", key=str(owner.pk))
    validator = FileUploadValidator(
        allowed_mime_types=social_settings.get("MEDIA_MIME_TYPES"),
        max_bytes=social_settings.get("MEDIA_MAX_BYTES"),
    )
    try:
        mime = validator(file)
    except DjangoValidationError as exc:
        raise ValidationError(details={"file": exc.messages}) from None
    width, height = _dimensions(file)
    media = PostMedia(
        owner=owner,
        mime_type=mime,
        size=file.size,
        width=width,
        height=height,
        alt_text=(alt_text or "").strip()[:500],
    )
    media._upload_file = file  # extension derives from content, not the client name
    media.file.save(file.name, file, save=False)
    media.save()
    return media


@transaction.atomic
def delete_media(*, owner: Any, media_id: Any) -> None:
    media = PostMedia.objects.filter(pk=media_id, owner=owner, post__isnull=True).first()
    if media is None:
        raise NotFound("Media not found.")
    media.file.delete(save=False)
    media.delete()


def claim_media(owner: Any, media_ids: list[Any]) -> list[PostMedia]:
    """Resolve upload ids for a new post — only the owner's unattached media."""
    if not media_ids:
        return []
    limit = int(social_settings.get("MAX_MEDIA_PER_POST", 4))
    if len(media_ids) > limit:
        raise ValidationError(details={"media": [f"Attach at most {limit} items."]})
    unique_ids = list(dict.fromkeys(str(m) for m in media_ids))
    found = {
        str(m.pk): m
        for m in PostMedia.objects.select_for_update().filter(pk__in=unique_ids, owner=owner, post__isnull=True)
    }
    if len(found) != len(unique_ids):
        raise ValidationError(details={"media": ["Unknown or unavailable media."]})
    return [found[i] for i in unique_ids]
