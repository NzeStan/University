"""Core hook implementations: export and purge."""

from __future__ import annotations

from typing import Any


def export_data(user: Any) -> dict[str, Any]:
    from university.media.models import MediaAsset

    return {
        "media": [
            {
                "kind": a.kind,
                "name": a.original_name,
                "mime_type": a.mime_type,
                "size": a.size,
                "status": a.status,
                "uploaded_at": a.created_at.isoformat(),
            }
            for a in MediaAsset.objects.filter(owner=user)
        ]
    }


def purge(user_id: Any) -> None:
    """Delete everything the person uploaded, files included."""
    from django.db import transaction

    from university.media.models import MediaAsset
    from university.media.services import remove_asset

    for asset in MediaAsset.objects.filter(owner_id=user_id):
        with transaction.atomic():
            remove_asset(asset)
