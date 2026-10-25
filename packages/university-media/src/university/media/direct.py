"""Direct-to-storage uploads for large files (spec: object storage, never the app server's disk).

The client asks for an upload slot, PUTs the file straight to object storage
with a short-lived presigned URL, then calls "complete". The server checks the
stored object's size and content signature before it becomes an asset.

Configure with ``MEDIA.DIRECT_UPLOADS``::

    "DIRECT_UPLOADS": {
        "class": "university.media.direct.S3DirectUploadProvider",
        "options": {"bucket": "uni-private", "region": "af-south-1"},
    }

The bucket must be the one behind ``MEDIA.STORAGE``. Credentials come from the
standard AWS environment/instance configuration (boto3), never from settings.
"""

from __future__ import annotations

from typing import Any, Protocol


class DirectUploadProvider(Protocol):
    def presign(self, *, key: str, mime_type: str, size: int, ttl_seconds: int) -> dict[str, Any]:
        """Return ``{"url", "method", "headers"}`` for the client's upload."""

    def stored_size(self, key: str) -> int | None:
        """Size of the uploaded object, or ``None`` if it isn't there."""


class S3DirectUploadProvider:
    def __init__(self, *, bucket: str, region: str | None = None, endpoint_url: str | None = None) -> None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("S3DirectUploadProvider needs boto3 (pip install boto3).") from exc
        self.bucket = bucket
        self.client = boto3.client("s3", region_name=region, endpoint_url=endpoint_url)

    def presign(self, *, key: str, mime_type: str, size: int, ttl_seconds: int) -> dict[str, Any]:
        url = self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": mime_type, "ContentLength": size},
            ExpiresIn=ttl_seconds,
        )
        return {"url": url, "method": "PUT", "headers": {"Content-Type": mime_type}}

    def stored_size(self, key: str) -> int | None:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception:
            return None
        return int(head.get("ContentLength") or 0)


def get_direct_upload_provider() -> DirectUploadProvider | None:
    from django.utils.module_loading import import_string

    from university.media.conf import media_settings

    conf = media_settings.get("DIRECT_UPLOADS")
    if not conf:
        return None
    return import_string(conf["class"])(**(conf.get("options") or {}))
