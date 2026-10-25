"""Media services: uploads, processing, clips, signed links and clean-up.

Uploads are validated by content signature against the kind's allow-list,
size-limited, checked against the owner's storage quota, hashed (SHA-256)
and stored privately under random names. Processing (probe, renditions,
constraints such as maximum duration and dimensions) runs on the task
backend; the asset becomes ``ready`` or ``failed``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import secrets
import shutil
import tempfile
import time
from typing import Any

from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files import File
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.ratelimit import rate_limit
from university.core.tasks import enqueue, task
from university.core.uploads import FileUploadValidator, safe_extension, sniff_mime_type
from university.media.conf import media_settings
from university.media.models import AssetStatus, DirectUpload, MediaAsset, MediaVariant, media_storage
from university.media.processing import ProcessingError, get_processor

logger = logging.getLogger("university.media")
SIGNING_SALT = "university.media.file"


def _kinds() -> dict[str, dict[str, Any]]:
    return media_settings.get("KINDS") or {}


def kind_for_mime(mime: str | None) -> str | None:
    for kind, conf in _kinds().items():
        if mime and mime in (conf.get("mime_types") or []):
            return kind
    return None


def _clean_name(name: str) -> str:
    base = os.path.basename(name or "")[:120]
    return "".join(ch for ch in base if ch.isprintable() and ch not in '\\/:*?"<>|')


def _check_quota(owner: Any, incoming: int) -> None:
    quota = media_settings.get("STORAGE_QUOTA_BYTES_PER_USER")
    if not quota:
        return
    used = MediaAsset.objects.filter(owner=owner).aggregate(total=Sum("size"))["total"] or 0
    if used + incoming > int(quota):
        raise ValidationError(
            "You've used your media storage.", code="quota_exceeded", details={"used": used, "quota": quota}
        )


def _check_pending(owner: Any) -> None:
    limit = int(media_settings.get("MAX_PENDING_PER_USER", 10))
    pending = MediaAsset.objects.filter(owner=owner, status__in=[AssetStatus.PENDING, AssetStatus.PROCESSING]).count()
    if pending >= limit:
        raise ValidationError("Wait for your other uploads to finish processing.", code="too_many_pending")


def _sha256(fileobj: Any) -> str:
    digest = hashlib.sha256()
    if hasattr(fileobj, "seek"):
        fileobj.seek(0)
    for chunk in iter(lambda: fileobj.read(1024 * 1024), b""):
        digest.update(chunk)
    if hasattr(fileobj, "seek"):
        fileobj.seek(0)
    return digest.hexdigest()


@transaction.atomic
def upload(*, owner: Any, file: Any, kind: str | None = None) -> MediaAsset:
    rate_limit("media_upload", key=str(owner.pk))
    head = file.read(2048)
    file.seek(0)
    detected = kind_for_mime(sniff_mime_type(head))
    kind = kind or detected
    if kind not in _kinds():
        raise ValidationError(details={"file": ["This type of file isn't supported."]}, code="unsupported_media")
    conf = _kinds()[kind]
    validator = FileUploadValidator(
        allowed_mime_types=conf.get("mime_types"),
        max_bytes=conf.get("max_bytes"),
        max_image_pixels=conf.get("max_pixels"),
    )
    try:
        mime = validator(file)
    except DjangoValidationError as exc:
        raise ValidationError(details={"file": exc.messages}, code="invalid_media") from None
    _check_pending(owner)
    _check_quota(owner, file.size)
    asset = MediaAsset(
        owner=owner,
        kind=kind,
        mime_type=mime,
        size=file.size,
        sha256=_sha256(file),
        original_name=_clean_name(file.name),
    )
    asset._upload_file = file
    asset.file.save(f"upload.{safe_extension(mime)}", file, save=False)
    asset.save()
    transaction.on_commit(lambda: enqueue(process_asset, str(asset.pk)))
    return asset


@transaction.atomic
def delete_asset(*, user: Any, asset_id: Any) -> None:
    asset = MediaAsset.objects.select_for_update().filter(pk=asset_id, owner=user).first()
    if asset is None:
        raise NotFound("Media not found.")
    if asset.attachments.exists():
        raise Conflict("This media is in use.", code="media_in_use")
    remove_asset(asset)


def remove_asset(asset: MediaAsset) -> None:
    """Delete an asset and its files (after commit, so a rollback keeps them)."""
    names = [asset.file.name, *asset.variants.values_list("file", flat=True)]
    storage = media_storage()
    asset.delete()

    def _delete() -> None:
        for name in names:
            if name:
                try:
                    storage.delete(name)
                except Exception:
                    logger.warning("Could not delete media file %s", name)

    transaction.on_commit(_delete)


# --------------------------------------------------------------- processing
def _download(asset: MediaAsset, workdir: str) -> str:
    path = os.path.join(workdir, f"source.{safe_extension(asset.mime_type)}")
    with asset.file.open("rb") as src, open(path, "wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    return path


def _enforce(asset: MediaAsset) -> None:
    conf = _kinds().get(asset.kind, {})
    max_duration = conf.get("max_duration_seconds")
    if max_duration and asset.duration_seconds and asset.duration_seconds > max_duration:
        raise ProcessingError("too_long")
    max_pixels = conf.get("max_pixels")
    if max_pixels and asset.width and asset.height and asset.width * asset.height > max_pixels:
        raise ProcessingError("too_large")


def _save_variant(asset: MediaAsset, name: str, path: str, mime: str) -> None:
    variant = MediaVariant(asset=asset, name=name, mime_type=mime, size=os.path.getsize(path))
    with open(path, "rb") as fh:
        variant.file.save(f"{name}.{safe_extension(mime)}", File(fh), save=False)
    variant.save()


@task(name="university.media.process_asset")
def process_asset(asset_id: str) -> None:
    if not MediaAsset.objects.filter(pk=asset_id, status=AssetStatus.PENDING).update(
        status=AssetStatus.PROCESSING, updated_at=timezone.now()
    ):
        return  # Claimed elsewhere or already done.
    asset = MediaAsset.objects.get(pk=asset_id)
    workdir = tempfile.mkdtemp(prefix="univ-media-")
    try:
        processor = get_processor()
        if not asset.source_id:
            source = _download(asset, workdir)
        else:  # A clip: cut it from the source first.
            out, mime = processor.clip(
                kind=asset.kind,
                mime_type=asset.source.mime_type,
                source=_download(asset.source, workdir),
                start=asset.clip_start or 0,
                end=asset.clip_end or 0,
                workdir=workdir,
            )
            with open(out, "rb") as fh:
                asset.file.save(f"clip.{safe_extension(mime)}", File(fh), save=False)
            asset.mime_type, asset.size = mime, os.path.getsize(out)
            source = out
        result = processor.process(kind=asset.kind, mime_type=asset.mime_type, source=source, workdir=workdir)
        asset.duration_seconds = result.duration_seconds or asset.duration_seconds
        asset.width, asset.height = result.width or asset.width, result.height or asset.height
        _enforce(asset)
        for name, path, mime in result.variants:
            _save_variant(asset, name, path, mime)
        asset.status = AssetStatus.READY
        asset.error = ""
    except ProcessingError as exc:
        asset.status, asset.error = AssetStatus.FAILED, exc.code
    except Exception:
        logger.exception("Processing media %s failed", asset_id)
        asset.status, asset.error = AssetStatus.FAILED, "processing_error"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    asset.processed_at = timezone.now()
    asset.save()
    event = "media.asset.ready" if asset.status == AssetStatus.READY else "media.asset.failed"
    publish(event, {"asset_id": asset.pk, "owner_id": asset.owner_id, "kind": asset.kind, "error": asset.error})


@transaction.atomic
def create_clip(*, owner: Any, asset_id: Any, start: float, end: float) -> MediaAsset:
    source = MediaAsset.objects.filter(pk=asset_id, owner=owner).first()
    if source is None:
        raise NotFound("Media not found.")
    if source.status != AssetStatus.READY:
        raise Conflict("The media is still processing.", code="media_not_ready")
    if not get_processor().supports_clip(kind=source.kind, mime_type=source.mime_type):
        raise Conflict("Clips aren't available for this media.", code="clips_unsupported")
    max_len = float(media_settings.get("CLIP_MAX_SECONDS", 180))
    if start < 0 or end <= start or end - start > max_len:
        raise ValidationError(details={"end": [f"Clips are up to {int(max_len)} seconds and end after they start."]})
    if source.duration_seconds is not None and end > source.duration_seconds + 0.5:
        raise ValidationError(details={"end": ["Past the end of the media."]})
    _check_pending(owner)
    clip = MediaAsset(
        owner=owner,
        kind=source.kind,
        mime_type=source.mime_type,
        size=0,
        original_name=f"clip-{source.original_name}"[:120],
        source=source,
        clip_start=start,
        clip_end=end,
        file="",  # Gets its own file when cut.
    )
    clip.save()
    transaction.on_commit(lambda: enqueue(process_asset, str(clip.pk)))
    return clip


# ---------------------------------------------------------- direct uploads
@transaction.atomic
def start_direct_upload(
    *, owner: Any, kind: str, mime_type: str, size: int, filename: str = ""
) -> tuple[DirectUpload, dict]:
    from university.media.direct import get_direct_upload_provider

    provider = get_direct_upload_provider()
    if provider is None:
        raise Conflict("Direct uploads aren't enabled.", code="direct_uploads_disabled")
    rate_limit("media_upload", key=str(owner.pk))
    conf = _kinds().get(kind)
    if conf is None or mime_type not in (conf.get("mime_types") or []):
        raise ValidationError(details={"mime_type": ["Not allowed for this kind."]})
    if not 0 < size <= int(conf.get("max_bytes")):
        raise ValidationError(details={"size": ["Too large."]}, code="file_too_large")
    _check_pending(owner)
    _check_quota(owner, size)
    ttl = int(media_settings.get("DIRECT_UPLOAD_TTL_SECONDS", 900))
    now = timezone.now()
    key = f"media/originals/{now:%Y}/{now:%m}/{secrets.token_hex(16)}.{safe_extension(mime_type)}"
    upload_row = DirectUpload.objects.create(
        owner=owner,
        kind=kind,
        key=key,
        declared_mime_type=mime_type,
        expected_size=size,
        original_name=_clean_name(filename),
        expires_at=now + dt.timedelta(seconds=ttl),
    )
    return upload_row, provider.presign(key=key, mime_type=mime_type, size=size, ttl_seconds=ttl)


@transaction.atomic
def complete_direct_upload(*, owner: Any, upload_id: Any) -> MediaAsset:
    from university.core.uploads import is_dangerous
    from university.media.direct import get_direct_upload_provider

    row = DirectUpload.objects.select_for_update().filter(pk=upload_id, owner=owner).first()
    if row is None:
        raise NotFound("Upload not found.")
    if row.status != DirectUpload.Status.PENDING:
        raise Conflict("This upload was already completed.", code="already_completed")
    provider = get_direct_upload_provider()
    stored = provider.stored_size(row.key) if provider else None
    storage = media_storage()
    reason = None
    if stored is None:
        reason = "not_uploaded"
    elif stored != row.expected_size:
        reason = "size_mismatch"
    else:
        with storage.open(row.key, "rb") as fh:
            head = fh.read(2048)
        mime = sniff_mime_type(head)
        if is_dangerous(head) or mime not in (_kinds()[row.kind].get("mime_types") or []):
            reason = "file_type_not_allowed"
    if reason:
        row.status = DirectUpload.Status.FAILED
        row.save(update_fields=["status", "updated_at"])
        if stored is not None:
            transaction.on_commit(lambda: storage.delete(row.key))
        raise ValidationError("The uploaded file was rejected.", code=reason)
    asset = MediaAsset.objects.create(
        owner=owner, kind=row.kind, mime_type=mime, size=stored, original_name=row.original_name, file=row.key
    )
    row.status = DirectUpload.Status.COMPLETED
    row.asset = asset
    row.save(update_fields=["status", "asset", "updated_at"])
    transaction.on_commit(lambda: enqueue(process_asset, str(asset.pk)))
    return asset


# ------------------------------------------------------------ signed links
def signed_token(asset_id: Any, variant: str, ttl_seconds: int | None = None) -> str:
    ttl = int(ttl_seconds or media_settings.get("SIGNED_URL_TTL_SECONDS", 3600))
    return signing.dumps(
        {"a": str(asset_id), "v": variant, "e": int(time.time()) + ttl}, salt=SIGNING_SALT, compress=True
    )


def read_token(token: str) -> tuple[str, str]:
    try:
        data = signing.loads(token, salt=SIGNING_SALT)
    except signing.BadSignature:
        raise NotFound() from None
    if int(data.get("e", 0)) < time.time():
        raise PermissionDenied("This link has expired.", code="link_expired")
    return data["a"], data["v"]


def file_for(asset: MediaAsset, variant: str) -> tuple[Any, str, int]:
    """(FieldFile, mime type, size) for a rendition, falling back to the original."""
    if variant and variant != "original":
        found = asset.variants.filter(name=variant).first()
        if found is not None:
            return found.file, found.mime_type, found.size
    return asset.file, asset.mime_type, asset.size


# ---------------------------------------------------------------- clean-up
def purge_orphans(cutoff: Any, dry_run: bool) -> int:
    qs = MediaAsset.objects.filter(created_at__lt=cutoff, attachments__isnull=True)
    if dry_run:
        return qs.count()
    count = 0
    for asset in qs.iterator():
        with transaction.atomic():
            remove_asset(asset)
        count += 1
    return count


def purge_failed(cutoff: Any, dry_run: bool) -> int:
    qs = MediaAsset.objects.filter(status=AssetStatus.FAILED, updated_at__lt=cutoff)
    if dry_run:
        return qs.count()
    count = 0
    for asset in qs.iterator():
        with transaction.atomic():
            remove_asset(asset)
        count += 1
    return count
