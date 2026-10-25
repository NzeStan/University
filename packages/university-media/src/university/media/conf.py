"""Settings for the media module (``UNIVERSITY["MEDIA"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

MB = 1024 * 1024

DEFAULTS: dict[str, Any] = {
    # What may be uploaded, per kind. Types are checked by content signature, not by name or header.
    "KINDS": {
        "audio": {
            "mime_types": ["audio/mpeg", "audio/mp4", "audio/aac", "audio/ogg", "audio/wav", "audio/flac"],
            "max_bytes": 500 * MB,
            "max_duration_seconds": 4 * 3600,
        },
        "video": {
            "mime_types": ["video/mp4", "video/quicktime", "video/webm"],
            "max_bytes": 2048 * MB,
            "max_duration_seconds": 4 * 3600,
            "max_pixels": 3840 * 2160,
        },
        "image": {
            "mime_types": ["image/jpeg", "image/png", "image/webp", "image/gif"],
            "max_bytes": 10 * MB,
            "max_pixels": 40_000_000,
        },
        "document": {"mime_types": ["application/pdf"], "max_bytes": 25 * MB},
    },
    # Django storage alias for originals and renditions (keep it private: S3 with querystring auth, MinIO …).
    "STORAGE": "private",
    # "signed": stream through Django with signed, expiring links (works with any storage);
    # "storage": hand out the storage's own URLs (e.g. S3 presigned URLs or a signed CDN).
    "SERVE_MODE": "signed",
    "SIGNED_URL_TTL_SECONDS": 3600,
    # Prefix for signed links when an absolute URL is needed (e.g. "https://api.example.edu").
    "PUBLIC_BASE_URL": "",
    # Processing (asynchronous, on the task backend). FFmpegProcessor transcodes audio/video.
    "PROCESSOR": "university.media.processing.BasicProcessor",
    "PROCESSOR_OPTIONS": {},
    # Direct-to-storage uploads for large files (e.g. S3 presigned PUTs). None disables them.
    "DIRECT_UPLOADS": None,
    "DIRECT_UPLOAD_TTL_SECONDS": 900,
    "STORAGE_QUOTA_BYTES_PER_USER": 5 * 1024 * MB,
    "MAX_PENDING_PER_USER": 10,
    "CLIP_MAX_SECONDS": 180,
    # Uploaded but never attached to anything: deleted after this long.
    "ORPHAN_RETENTION_HOURS": 48,
    "FAILED_RETENTION_DAYS": 7,
}

media_settings = ModuleSettings("MEDIA", DEFAULTS)
