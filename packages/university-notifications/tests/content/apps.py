"""A stand-in content module (like university-social) for tests."""

from __future__ import annotations

from typing import Any

from university.core.content import ContentAdapter, ContentRef
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig

#: id -> {"author": user id | None, "label": str, "hidden_from": set of user ids}
ITEMS: dict[str, dict[str, Any]] = {}
#: (blocker id, blocked id)
BLOCKS: set[tuple[str, str]] = set()


class ItemAdapter(ContentAdapter):
    content_type = "test.item"
    label = "Test item"

    def resolve(self, object_id: Any) -> ContentRef | None:
        item = ITEMS.get(str(object_id))
        if item is None:
            return None
        author = item.get("author")
        return ContentRef(
            content_type=self.content_type,
            object_id=str(object_id),
            author_id=str(author) if author else None,
            is_anonymous=author is None,
            excerpt=item.get("label", ""),
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        item = ITEMS.get(str(object_id))
        return item is not None and str(getattr(viewer, "pk", "")) not in item.get("hidden_from", set())


def can_interact(actor: Any, target: Any, action: str) -> bool | None:
    pair = {(str(actor.pk), str(target.pk)), (str(target.pk), str(actor.pk))}
    return False if pair & BLOCKS else None


class ContentConfig(UniversityAppConfig):
    name = "tests.content"
    label = "test_content"
    module_name = "test_content"

    def get_content_adapters(self) -> list[Any]:
        return [ItemAdapter()]

    def register_hooks(self, hooks: HookRegistry) -> None:
        hooks.register(Hook.USER_CAN_INTERACT, can_interact)
