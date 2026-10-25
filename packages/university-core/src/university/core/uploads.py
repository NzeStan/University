"""Secure file upload validation and storage naming.

Never trust the client's ``Content-Type`` or file name. Uploads are checked
by size, by *content signature* (magic bytes) against an allow-list, and by
extension consistency; executables, scripts and active content (HTML, SVG)
are rejected unless explicitly allowed. Stored files get random names so a
client cannot choose a path (path traversal) or overwrite another file.

Usage on a model field::

    file = models.FileField(
        upload_to=uuid_upload_to("documents"),
        validators=[FileUploadValidator(allowed_mime_types=["application/pdf"])],
        storage=get_storage("private"),
    )
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _

from university.core.conf import university_settings

# (mime type, offset, signature bytes)
_SIGNATURES: list[tuple[str, int, bytes]] = [
    ("image/jpeg", 0, b"\xff\xd8\xff"),
    ("image/png", 0, b"\x89PNG\r\n\x1a\n"),
    ("image/gif", 0, b"GIF87a"),
    ("image/gif", 0, b"GIF89a"),
    ("application/pdf", 0, b"%PDF-"),
    ("audio/mpeg", 0, b"ID3"),
    ("audio/mpeg", 0, b"\xff\xfb"),
    ("audio/mpeg", 0, b"\xff\xf3"),  # MPEG-2 layer III
    ("audio/mpeg", 0, b"\xff\xf2"),  # MPEG-2.5 layer III
    ("audio/aac", 0, b"\xff\xf1"),  # AAC ADTS (MPEG-4)
    ("audio/aac", 0, b"\xff\xf9"),  # AAC ADTS (MPEG-2)
    ("audio/ogg", 0, b"OggS"),
    ("audio/flac", 0, b"fLaC"),
    ("application/zip", 0, b"PK\x03\x04"),
]

# Content that must never be accepted regardless of allow-list.
_DANGEROUS_PREFIXES: list[bytes] = [
    b"MZ",  # Windows PE
    b"\x7fELF",  # ELF
    b"\xcf\xfa\xed\xfe",  # Mach-O
    b"\xfe\xed\xfa\xce",
    b"#!",  # scripts
    b"\xca\xfe\xba\xbe",  # Java class / Mach-O fat
]
_ACTIVE_CONTENT_MARKERS = (b"<script", b"<html", b"<svg", b"<?php", b"<!doctype html")

EXTENSIONS: dict[str, tuple[str, ...]] = {
    "image/jpeg": ("jpg", "jpeg"),
    "image/png": ("png",),
    "image/gif": ("gif",),
    "image/webp": ("webp",),
    "application/pdf": ("pdf",),
    "audio/mpeg": ("mp3",),
    "audio/ogg": ("ogg", "oga", "opus"),
    "audio/wav": ("wav",),
    "audio/flac": ("flac",),
    "audio/mp4": ("m4a",),
    "audio/aac": ("aac",),
    "video/mp4": ("mp4", "m4v"),
    "video/quicktime": ("mov",),
    "video/webm": ("webm",),
    "application/zip": ("zip",),
}


def sniff_mime_type(head: bytes) -> str | None:
    """Identify a file type from its first bytes (at least 16 recommended)."""
    for mime, offset, sig in _SIGNATURES:
        if head[offset : offset + len(sig)] == sig:
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"M4A ", b"M4B "):
            return "audio/mp4"
        if brand == b"qt  ":
            return "video/quicktime"
        return "video/mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"
    return None


def is_dangerous(head: bytes) -> bool:
    if any(head.startswith(prefix) for prefix in _DANGEROUS_PREFIXES):
        return True
    lowered = head[:1024].lower().lstrip()
    return any(marker in lowered for marker in _ACTIVE_CONTENT_MARKERS)


def _read_head(file: Any, size: int = 2048) -> bytes:
    position = file.tell() if hasattr(file, "tell") else None
    try:
        if hasattr(file, "seek"):
            file.seek(0)
        head = file.read(size)
    finally:
        if position is not None and hasattr(file, "seek"):
            file.seek(position)
    return head if isinstance(head, bytes) else head.encode()


@deconstructible
class FileUploadValidator:
    """Validates size, real content type and extension of an uploaded file."""

    def __init__(
        self,
        *,
        allowed_mime_types: Iterable[str] | None = None,
        max_bytes: int | None = None,
        max_image_pixels: int | None = None,
    ) -> None:
        self.allowed_mime_types = list(allowed_mime_types) if allowed_mime_types else None
        self.max_bytes = max_bytes
        self.max_image_pixels = max_image_pixels

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, FileUploadValidator)
            and self.allowed_mime_types == other.allowed_mime_types
            and self.max_bytes == other.max_bytes
            and self.max_image_pixels == other.max_image_pixels
        )

    def __call__(self, file: Any) -> str:
        allowed = self.allowed_mime_types or university_settings.get("UPLOADS.ALLOWED_MIME_TYPES")
        max_bytes = self.max_bytes or university_settings.get("UPLOADS.MAX_BYTES")
        size = getattr(file, "size", None)
        if size is None or size <= 0:
            raise ValidationError(_("The uploaded file is empty."), code="empty_file")
        if size > max_bytes:
            raise ValidationError(
                _("The file is too large (maximum %(max)s bytes)."),
                code="file_too_large",
                params={"max": max_bytes},
            )
        head = _read_head(file)
        if is_dangerous(head):
            raise ValidationError(_("This type of file is not allowed."), code="dangerous_file")
        mime = sniff_mime_type(head)
        if mime is None or mime not in allowed:
            raise ValidationError(_("This type of file is not allowed."), code="file_type_not_allowed")
        name = getattr(file, "name", "") or ""
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        if ext and ext not in EXTENSIONS.get(mime, ()):
            raise ValidationError(_("The file extension does not match its content."), code="extension_mismatch")
        if mime.startswith("image/"):
            self._check_image(file)
        return mime

    def _check_image(self, file: Any) -> None:
        max_pixels = self.max_image_pixels or university_settings.get("UPLOADS.MAX_IMAGE_PIXELS")
        try:
            from PIL import Image
        except ImportError:  # Pillow is optional; signature checks still apply.
            return
        position = file.tell() if hasattr(file, "tell") else None
        try:
            file.seek(0)
            with Image.open(file) as image:
                width, height = image.size
                image.verify()
        except Exception as exc:
            raise ValidationError(_("The image is corrupt or unsupported."), code="invalid_image") from exc
        finally:
            if position is not None:
                file.seek(position)
        if width * height > max_pixels:
            raise ValidationError(_("The image dimensions are too large."), code="image_too_large")


def safe_extension(mime_type: str) -> str:
    return EXTENSIONS.get(mime_type, ("bin",))[0]


@deconstructible
class uuid_upload_to:
    """``upload_to`` callable producing ``<prefix>/<yyyy>/<mm>/<uuid>.<ext>``.

    The extension is derived from the sniffed content type, never from the
    client-supplied name.
    """

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix.strip("/")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, uuid_upload_to) and self.prefix == other.prefix

    def __call__(self, instance: Any, filename: str) -> str:
        ext = os.path.splitext(filename)[1].lower().lstrip(".")
        file = getattr(instance, "_upload_file", None)
        if file is not None:
            mime = sniff_mime_type(_read_head(file))
            if mime:
                ext = safe_extension(mime)
        if not ext.isalnum() or len(ext) > 8:
            ext = "bin"
        now = timezone.now()
        return f"{self.prefix}/{now:%Y}/{now:%m}/{uuid.uuid4().hex}.{ext}"
