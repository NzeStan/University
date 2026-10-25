"""Test doubles: a direct-upload provider backed by the configured storage."""

from __future__ import annotations

from typing import Any


class StorageDirectUploads:
    def __init__(self, **_: Any) -> None:
        pass

    def presign(self, *, key: str, mime_type: str, size: int, ttl_seconds: int) -> dict[str, Any]:
        return {"url": f"https://storage.test.invalid/{key}", "method": "PUT", "headers": {"Content-Type": mime_type}}

    def stored_size(self, key: str) -> int | None:
        from university.media.models import media_storage

        storage = media_storage()
        return storage.size(key) if storage.exists(key) else None
