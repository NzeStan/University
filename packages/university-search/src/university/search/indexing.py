"""Keep the index in step with content, using ids-only events and content adapters.

Documents carry visibility tags:

* ``public`` when an anonymous visitor may see the item;
* ``<scope_type>:<scope_id>`` when it's limited to an audience (an
  institution, a community …);
* ``restricted`` otherwise (drafts, hidden items) — no viewer carries this
  tag, so such items are never returned.

Tags only narrow candidates: the search service re-checks every hit with the
item's content adapter for the actual viewer.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from university.core.events import Event
from university.core.providers.search import SearchDocument
from university.core.tasks import enqueue, task
from university.search.backends import get_backend
from university.search.conf import search_settings

logger = logging.getLogger("university.search")


def build_document(content_type: str, object_id: str) -> SearchDocument | None:
    from university.core.registry import registry

    adapter = registry.content_adapters.get(content_type)
    ref = adapter.resolve(object_id) if adapter else None
    if ref is None:
        return None
    if adapter.can_view(None, object_id):
        tags = ["public"]
    elif ref.scope:
        tags = [f"{ref.scope[0]}:{ref.scope[1]}"]
    else:
        tags = ["restricted"]
    lines = (ref.excerpt or "").strip().splitlines() or [""]
    return SearchDocument(
        index=content_type,
        id=str(object_id),
        body={
            "title": lines[0][:200],
            "body": ref.excerpt or "",
            # Never link anonymous content to anyone.
            "author_id": "" if ref.is_anonymous else (ref.author_id or ""),
        },
        visibility=tags,
    )


@task(name="university.search.index_item")
def index_item(content_type: str, object_id: str) -> None:
    backend = get_backend()
    doc = build_document(content_type, object_id)
    if doc is None:
        backend.delete(content_type, [object_id])
    else:
        backend.index([doc])


@task(name="university.search.remove_item")
def remove_item(content_type: str, object_id: str) -> None:
    get_backend().delete(content_type, [object_id])


def _rules() -> dict[str, tuple[str, str, str]]:
    """event name -> (content type, id key, action)"""
    rules: dict[str, tuple[str, str, str]] = {}
    for content_type, conf in (search_settings.get("SOURCES") or {}).items():
        for name in conf.get("index") or []:
            rules[name] = (content_type, conf["id_key"], "index")
        for name in conf.get("remove") or []:
            rules[name] = (content_type, conf["id_key"], "remove")
    return rules


def handle_event(event: Event) -> None:
    rule = _rules().get(event.name)
    if rule is None:
        return
    content_type, id_key, action = rule
    object_id = event.payload.get(id_key)
    if not object_id:
        return
    job = index_item if action == "index" else remove_item
    if search_settings.get("ASYNC_INDEXING", True):
        enqueue(job, content_type, str(object_id))
    else:
        job(content_type, str(object_id))


def event_names() -> Iterable[str]:
    return list(_rules())


def reindex(content_types: Iterable[str] | None = None) -> int:
    """Index every live item of the given types (via ``ContentAdapter.iter_ids``)."""
    from university.core.registry import registry

    wanted = list(content_types or (search_settings.get("SOURCES") or {}).keys())
    count = 0
    for content_type in wanted:
        adapter = registry.content_adapters.get(content_type)
        if adapter is None:
            continue
        for object_id in adapter.iter_ids():
            try:
                index_item(content_type, str(object_id))
                count += 1
            except Exception:
                logger.exception("Indexing %s:%s failed", content_type, object_id)
    return count


def purge_author(user_id: Any) -> None:
    backend = get_backend()
    remover = getattr(backend, "delete_by_author", None)
    if remover is not None:
        remover(str(user_id))
