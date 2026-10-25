"""Search services: content search and people search, both enumeration-resistant (spec §90).

* Content results are re-checked against the viewer with each item's content
  adapter, so private communities, audience-only posts, hidden content and
  blocked people never appear — whatever the index holds.
* People search matches handles and display names only (never email or
  phone), requires a longer query, respects ``searchable`` and profile
  privacy, caps results and is rate-limited.
* Bad input gets the same generic response as no results.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Q

from university.core.audiences import member_scopes
from university.core.exceptions import ValidationError
from university.core.providers.search import SearchQuery
from university.core.ratelimit import rate_limit
from university.search.backends import get_backend
from university.search.conf import search_settings

logger = logging.getLogger("university.search")


def _clean(q: str, minimum: int) -> str:
    q = " ".join((q or "").split())
    maximum = int(search_settings.get("MAX_QUERY_LENGTH", 100))
    if len(q) < minimum or len(q) > maximum:
        raise ValidationError(details={"q": [f"Search for {minimum} to {maximum} characters."]}, code="invalid_query")
    return q


def _who(viewer: Any, fingerprint: str) -> str:
    return f"u:{viewer.pk}" if getattr(viewer, "is_authenticated", False) else f"a:{fingerprint}"


def visibility_tags(viewer: Any) -> list[str]:
    tags = ["public"]
    if getattr(viewer, "is_authenticated", False):
        tags += [f"{scope_type}:{scope_id}" for scope_type, scope_id in member_scopes(viewer)]
    return tags


def search(
    *, viewer: Any, q: str, types: Iterable[str] = (), limit: int = 20, fingerprint: str = ""
) -> list[dict[str, Any]]:
    from university.core.registry import registry

    q = _clean(q, int(search_settings.get("MIN_QUERY_LENGTH", 2)))
    rate_limit("search", key=_who(viewer, fingerprint))
    limit = max(1, min(limit, int(search_settings.get("MAX_RESULTS", 50))))
    allowed = set(search_settings.get("SOURCES") or {})
    types = [t for t in types if t in allowed] if types else []
    hits = get_backend().search(
        SearchQuery(index="", text=q, filters={"types": types}, visibility=visibility_tags(viewer), limit=limit * 3)
    )
    results = []
    for hit in hits:
        adapter = registry.content_adapters.get(hit.index)
        if adapter is None:
            continue
        try:
            if not adapter.can_view(viewer, hit.id):
                continue  # The definitive check for this viewer.
            ref = adapter.resolve(hit.id)
        except Exception:
            logger.exception("Visibility check failed; hiding the hit.", extra={"index": hit.index})
            continue  # Fail closed.
        if ref is None:
            continue
        lines = (ref.excerpt or "").strip().splitlines() or [""]
        results.append(
            {
                "content_type": hit.index,
                "object_id": hit.id,
                "title": lines[0][:200],
                "snippet": " ".join(lines[1:])[:300],
                "score": round(hit.score, 4),
            }
        )
        if len(results) >= limit:
            break
    return results


def people(*, viewer: Any, q: str, fingerprint: str = "") -> list[dict[str, Any]]:
    from university.users.selectors import can_view_profile

    q = _clean(q, int(search_settings.get("PEOPLE_MIN_QUERY_LENGTH", 3)))
    rate_limit("search_people", key=_who(viewer, fingerprint))
    if "@" in q and not q.startswith("@"):
        return []  # Looks like an email address: never searchable.
    needle = q.lstrip("@").lower()
    visibility = ["public", "members"] if getattr(viewer, "is_authenticated", False) else ["public"]
    candidates = (
        get_user_model()
        .objects.filter(
            is_active=True,
            privacy_settings__searchable=True,
            privacy_settings__profile_visibility__in=visibility,
        )
        .filter(Q(handle__istartswith=needle) | Q(display_name__icontains=needle))
        .order_by("handle")[: int(search_settings.get("PEOPLE_MAX_RESULTS", 20)) * 2]
    )
    results = []
    for user in candidates:
        if not can_view_profile(viewer, user):
            continue  # Blocks and other module rules.
        results.append({"id": user.pk, "handle": user.handle, "display_name": user.display_name or user.handle or ""})
        if len(results) >= int(search_settings.get("PEOPLE_MAX_RESULTS", 20)):
            break
    return results
