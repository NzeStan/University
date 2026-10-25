"""Storage helpers.

University stores files through Django's ``STORAGES`` setting so any backend
works (S3, MinIO, Cloudinary, GCS, Azure …). Keep public and private media in
separate storages/buckets::

    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": {...}},
        "private": {"BACKEND": "storages.backends.s3.S3Storage",
                    "OPTIONS": {"bucket_name": "uni-private", "querystring_auth": True}},
        "staticfiles": {...},
    }

Production deployments must not keep user media on the application server's
local disk — a system check warns when they do.
"""

from __future__ import annotations

from django.core.files.storage import Storage, storages
from django.core.files.storage.handler import InvalidStorageError

PUBLIC_STORAGE = "default"
PRIVATE_STORAGE = "private"


def get_storage(alias: str = PUBLIC_STORAGE) -> Storage:
    """Return the storage for ``alias``, falling back to ``default``."""
    try:
        return storages[alias]
    except InvalidStorageError:
        return storages[PUBLIC_STORAGE]


def get_private_storage() -> Storage:
    return get_storage(PRIVATE_STORAGE)


def private_storage() -> Storage:
    """Callable for ``FileField(storage=private_storage)`` (resolved lazily)."""
    return get_private_storage()
