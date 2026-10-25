"""This module's implementation of Core's media library contract."""

from __future__ import annotations

from typing import Any

from django.urls import reverse

from university.core.exceptions import Conflict, NotFound
from university.core.ids import is_valid_uuid
from university.core.media import MediaRef
from university.media.conf import media_settings
from university.media.models import AssetStatus, MediaAsset, MediaAttachment


def _ref(asset: MediaAsset) -> MediaRef:
    return MediaRef(
        id=str(asset.pk),
        kind=asset.kind,
        owner_id=str(asset.owner_id) if asset.owner_id else None,
        status=asset.status,
        mime_type=asset.mime_type,
        size=asset.size,
        duration_seconds=asset.duration_seconds,
        width=asset.width,
        height=asset.height,
        variants=("original", *asset.variants.values_list("name", flat=True)),
    )


def _get(media_id: Any) -> MediaAsset | None:
    return MediaAsset.objects.filter(pk=media_id).first() if is_valid_uuid(media_id) else None


class Library:
    def resolve(self, media_id: Any) -> MediaRef | None:
        asset = _get(media_id)
        return _ref(asset) if asset else None

    def attach(self, media_id: Any, *, owner: Any, purpose: str, object_id: Any) -> MediaRef:
        asset = _get(media_id)
        if asset is None or asset.owner_id != getattr(owner, "pk", None):
            raise NotFound("Media not found.")
        if asset.status == AssetStatus.FAILED:
            raise Conflict("This media failed processing.", code="media_failed")
        MediaAttachment.objects.get_or_create(asset=asset, purpose=purpose[:64], object_id=str(object_id)[:64])
        return _ref(asset)

    def detach(self, media_id: Any, *, purpose: str, object_id: Any) -> None:
        if is_valid_uuid(media_id):
            MediaAttachment.objects.filter(asset_id=media_id, purpose=purpose, object_id=str(object_id)).delete()

    def url(self, media_id: Any, *, variant: str = "original", ttl_seconds: int | None = None) -> str:
        from university.media.services import file_for, signed_token

        asset = _get(media_id)
        if asset is None:
            raise NotFound("Media not found.")
        if media_settings.get("SERVE_MODE") == "storage":
            fieldfile, _, _ = file_for(asset, variant)
            return fieldfile.url
        path = reverse("v1:media:file", kwargs={"token": signed_token(asset.pk, variant, ttl_seconds)})
        return f"{media_settings.get('PUBLIC_BASE_URL') or ''}{path}"

    def create_clip(self, media_id: Any, *, owner: Any, start_seconds: float, end_seconds: float) -> MediaRef:
        from university.media.services import create_clip

        return _ref(create_clip(owner=owner, asset_id=media_id, start=start_seconds, end=end_seconds))
