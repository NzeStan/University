"""The media library contract: how modules use stored media without depending on its module.

One installed module (normally university-media) contributes a
:class:`MediaLibrary` from its AppConfig::

    class MediaConfig(UniversityAppConfig):
        def get_media_library(self):
            return Library()

Consumers (podcasts, posts, listings …) keep media *ids* and go through Core::

    from university.core.media import require_media_library

    library = require_media_library()
    ref = library.attach(media_id, owner=user, purpose="podcast.episode", object_id=episode.pk)
    url = library.url(media_id, variant="mp3")   # short-lived, signed

Rules: assets belong to their uploader and can only be attached by them; an
asset is usable once ``status == "ready"`` (processing is asynchronous);
URLs are short-lived and only handed out by consumers that already decided the
viewer may see the content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from university.core.exceptions import ServiceUnavailable


@dataclass(frozen=True)
class MediaRef:
    id: str
    #: ``audio``, ``video``, ``image`` or ``document``.
    kind: str
    owner_id: str | None
    #: ``pending``, ``processing``, ``ready`` or ``failed``.
    status: str
    mime_type: str
    size: int
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    #: Available renditions, e.g. ``("original", "mp3", "poster")``.
    variants: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"


class MediaLibrary(Protocol):
    def resolve(self, media_id: Any) -> MediaRef | None: ...

    def attach(self, media_id: Any, *, owner: Any, purpose: str, object_id: Any) -> MediaRef:
        """Claim an asset for a use. Raises ``NotFound`` unless ``owner`` owns it."""

    def detach(self, media_id: Any, *, purpose: str, object_id: Any) -> None: ...

    def url(self, media_id: Any, *, variant: str = "original", ttl_seconds: int | None = None) -> str:
        """A short-lived URL for a rendition (falls back to the original)."""

    def create_clip(self, media_id: Any, *, owner: Any, start_seconds: float, end_seconds: float) -> MediaRef:
        """Start cutting a clip into a new asset (processed asynchronously)."""


def get_media_library() -> MediaLibrary | None:
    from university.core.registry import registry

    return registry.media_library


def require_media_library() -> MediaLibrary:
    library = get_media_library()
    if library is None:
        raise ServiceUnavailable("Media storage isn't available.", code="media_unavailable")
    return library


__all__ = ["MediaLibrary", "MediaRef", "get_media_library", "require_media_library"]
