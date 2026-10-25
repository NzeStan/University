"""Content adapters: a shared abstraction over every module's user content.

Cross-cutting modules (moderation, search, analytics) must act on content
from modules they don't know — social posts, anonymous posts, event
listings, marketplace items. Content modules describe each content type with
a :class:`ContentAdapter`, contributed from their AppConfig::

    class SocialConfig(UniversityAppConfig):
        def get_content_adapters(self):
            return [SocialPostAdapter(), SocialCommentAdapter()]

and consumers resolve them through Core::

    from university.core.content import get_adapter

    adapter = get_adapter("social.post")
    ref = adapter.resolve(object_id)

Neither side imports the other. Adapters for anonymous content return
``ContentRef(author_id=None, is_anonymous=True)`` — the identity is never
handed out through :meth:`ContentAdapter.resolve`.

Registering an adapter does **not** make content reportable. Many adapters
exist only so other modules can name and permission-check things (e.g. an
institution's display name in a notification). Taking part in moderation —
user reports, moderator-opened cases and actions — is an explicit opt-in,
:attr:`ContentAdapter.moderatable`, resolved with
:func:`get_moderatable_adapter`. Opting in is a policy decision: it must say
who investigates (``ContentRef.scope`` routes cases to that scope's
moderators) and which actions apply (implement ``hide``/``restore``/``remove``).

Content-creation restrictions (e.g. a moderation sanction "no posting for 7
days") go through :data:`Hook.USER_CAN_CREATE_CONTENT`; content modules call
:func:`ensure_can_create` before accepting new content.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from university.core.exceptions import NotFound, PermissionDenied
from university.core.hooks import Hook, hooks


@dataclass(frozen=True)
class ContentRef:
    """A moderator-safe description of a content item."""

    content_type: str
    object_id: str
    #: The author's user id — always ``None`` for anonymous content.
    author_id: str | None
    is_anonymous: bool = False
    #: Audience scope ``(scope_type, scope_id)`` or ``None`` for platform-wide.
    scope: tuple[str, str] | None = None
    #: Text snapshot for reviewers (truncated).
    excerpt: str = ""
    status: str = ""
    created_at: dt.datetime | None = None


class ContentAdapter:
    """Describe one content type to cross-cutting modules.

    Subclasses implement :meth:`resolve`, :meth:`can_view` and the state
    changes. ``hide``/``restore``/``remove`` change state only; callers
    authorise and audit.
    """

    content_type: str = ""
    label: str = ""
    #: Whether this content type takes part in moderation (reports, cases,
    #: actions). Off by default: an adapter registered only for display and
    #: visibility checks is never reportable or sanctionable.
    moderatable: bool = False
    #: Permission additionally required to apply user-level sanctions to the
    #: author (e.g. for anonymous content, where that links author and item).
    sanction_permission: str | None = None

    def resolve(self, object_id: Any) -> ContentRef | None:
        raise NotImplementedError

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        raise NotImplementedError

    def hide(self, object_id: Any, *, reason: str) -> None:
        raise NotImplementedError

    def restore(self, object_id: Any) -> None:
        raise NotImplementedError

    def remove(self, object_id: Any, *, reason: str) -> None:
        raise NotImplementedError

    def iter_ids(self) -> Iterable[str]:
        """Ids of currently live items, for search backfills (optional; default: none)."""
        return ()

    def is_author(self, object_id: Any, user: Any) -> bool:
        ref = self.resolve(object_id)
        return bool(ref and ref.author_id and user is not None and ref.author_id == str(user.pk))

    def resolve_author(self, object_id: Any) -> Any:
        """The author's user object, for authorised sanctions only."""
        from django.contrib.auth import get_user_model

        ref = self.resolve(object_id)
        if ref is None or not ref.author_id:
            return None
        return get_user_model().all_objects.filter(pk=ref.author_id).first()


def get_adapter(content_type: str) -> ContentAdapter:
    from university.core.registry import registry

    adapter = registry.content_adapters.get(content_type)
    if adapter is None:
        raise NotFound("Unknown content type.")
    return adapter


def get_moderatable_adapter(content_type: str) -> ContentAdapter:
    """The adapter for a content type that opted in to moderation.

    Unknown and non-moderatable types are indistinguishable (both 404), so
    callers can't probe which display-only adapters exist.
    """
    from university.core.registry import registry

    adapter = registry.content_adapters.get(content_type)
    if adapter is None or not adapter.moderatable:
        raise NotFound("Unknown content type.")
    return adapter


def content_types(*, moderatable: bool | None = None) -> list[str]:
    from university.core.registry import registry

    adapters = registry.content_adapters
    if moderatable is None:
        return sorted(adapters)
    return sorted(k for k, a in adapters.items() if bool(a.moderatable) is moderatable)


def can_create_content(user: Any, content_type: str) -> bool:
    return hooks.allows(Hook.USER_CAN_CREATE_CONTENT, user, content_type)


def ensure_can_create(user: Any, content_type: str) -> None:
    if not can_create_content(user, content_type):
        raise PermissionDenied(
            "You are currently restricted from creating this kind of content.",
            code="content_creation_restricted",
        )


__all__ = [
    "ContentAdapter",
    "ContentRef",
    "can_create_content",
    "content_types",
    "ensure_can_create",
    "get_adapter",
    "get_moderatable_adapter",
]
