"""Search backends implementing Core's :class:`~university.core.providers.search.SearchBackend`.

* :class:`DatabaseSearchBackend` — no extra infrastructure. On PostgreSQL it
  uses full-text search (``websearch`` queries, weighted title/body, ranking);
  elsewhere it falls back to token matching.
* :class:`OpenSearchBackend` — OpenSearch or Elasticsearch over HTTPS (Core's
  hardened HTTP client: TLS only, timeouts, no redirects).

Both store the visibility tags of each document and filter on them; the
search service additionally re-checks every hit against the viewer.
"""

from __future__ import annotations

import base64
import urllib.parse
from collections.abc import Iterable
from typing import Any

from django.db import connection
from django.db.models import Q

from university.core.exceptions import ProviderError
from university.core.providers.http import request
from university.core.providers.search import SearchDocument, SearchHit, SearchQuery
from university.search.models import SearchEntry


def _types(query: SearchQuery) -> list[str]:
    types = list(query.filters.get("types") or [])
    if query.index:
        types.append(query.index)
    return types


class DatabaseSearchBackend:
    def __init__(self, **_: Any) -> None:
        pass

    def index(self, documents: Iterable[SearchDocument]) -> None:
        for doc in documents:
            body = dict(doc.body)
            SearchEntry.objects.update_or_create(
                index=doc.index,
                object_id=str(doc.id),
                defaults={
                    "title": str(body.get("title", ""))[:200],
                    "body": str(body.get("body", ""))[:20000],
                    "author_id": str(body.get("author_id") or "")[:64],
                    "tags": " " + " ".join(sorted(set(doc.visibility))) + " ",
                },
            )

    def delete(self, index: str, ids: Iterable[str]) -> None:
        SearchEntry.objects.filter(index=index, object_id__in=[str(i) for i in ids]).delete()

    def delete_by_author(self, author_id: str) -> None:
        SearchEntry.objects.filter(author_id=author_id).delete()

    def search(self, query: SearchQuery) -> list[SearchHit]:
        tag_filter = Q()
        for tag in query.visibility:
            tag_filter |= Q(tags__contains=f" {tag} ")
        qs = SearchEntry.objects.filter(tag_filter)
        if types := _types(query):
            qs = qs.filter(index__in=types)
        if connection.vendor == "postgresql":
            return self._postgres(qs, query)
        return self._portable(qs, query)

    def _postgres(self, qs: Any, query: SearchQuery) -> list[SearchHit]:  # pragma: no cover - needs PostgreSQL
        from django.contrib.postgres.search import SearchQuery as PGQuery
        from django.contrib.postgres.search import SearchRank, SearchVector

        vector = SearchVector("title", weight="A") + SearchVector("body", weight="B")
        pg_query = PGQuery(query.text, search_type="websearch")
        rows = (
            qs.annotate(rank=SearchRank(vector, pg_query))
            .filter(rank__gt=0)
            .order_by("-rank", "-updated_at")[query.offset : query.offset + query.limit]
        )
        return [SearchHit(index=r.index, id=r.object_id, score=float(r.rank)) for r in rows]

    def _portable(self, qs: Any, query: SearchQuery) -> list[SearchHit]:
        tokens = [t for t in query.text.lower().split() if t][:10]
        for token in tokens:
            qs = qs.filter(Q(title__icontains=token) | Q(body__icontains=token))
        hits = []
        for row in qs.order_by("-updated_at")[: (query.offset + query.limit) * 4]:
            title, body = row.title.lower(), row.body.lower()
            score = sum(3.0 * title.count(t) + body.count(t) for t in tokens) or 0.1
            hits.append(SearchHit(index=row.index, id=row.object_id, score=score))
        hits.sort(key=lambda h: -h.score)
        return hits[query.offset : query.offset + query.limit]


class OpenSearchBackend:
    """OpenSearch / Elasticsearch (7+, 8+) via the REST API."""

    def __init__(
        self,
        *,
        url: str,
        index_prefix: str = "university",
        username: str = "",
        password: str = "",
        api_key: str = "",
        timeout: int = 10,
    ) -> None:
        self.url = url.rstrip("/")
        self.prefix = index_prefix
        self.timeout = timeout
        if api_key:
            self.auth = {"Authorization": f"ApiKey {api_key}"}
        elif username:
            token = base64.b64encode(f"{username}:{password}".encode()).decode()
            self.auth = {"Authorization": f"Basic {token}"}
        else:
            self.auth = {}

    def _index_name(self, index: str) -> str:
        return f"{self.prefix}-{index.replace('.', '_')}"

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        return request(method, f"{self.url}{path}", json_body=body, headers=self.auth, timeout=self.timeout)

    def index(self, documents: Iterable[SearchDocument]) -> None:
        for doc in documents:
            body = dict(doc.body)
            self._call(
                "PUT",
                f"/{self._index_name(doc.index)}/_doc/{urllib.parse.quote(str(doc.id), safe='')}",
                {
                    "content_type": doc.index,
                    "title": body.get("title", ""),
                    "body": body.get("body", ""),
                    "author_id": body.get("author_id") or "",
                    "tags": list(doc.visibility),
                },
            )

    def delete(self, index: str, ids: Iterable[str]) -> None:
        for object_id in ids:
            try:
                self._call("DELETE", f"/{self._index_name(index)}/_doc/{urllib.parse.quote(str(object_id), safe='')}")
            except ProviderError as exc:
                if exc.details.get("status") != 404:
                    raise

    def delete_by_author(self, author_id: str) -> None:
        self._call("POST", f"/{self.prefix}-*/_delete_by_query", {"query": {"term": {"author_id": author_id}}})

    def search(self, query: SearchQuery) -> list[SearchHit]:
        filters: list[dict[str, Any]] = [{"terms": {"tags": list(query.visibility)}}]
        if types := _types(query):
            filters.append({"terms": {"content_type": types}})
        body = {
            "from": query.offset,
            "size": query.limit,
            "query": {
                "bool": {
                    "must": [
                        {"multi_match": {"query": query.text, "fields": ["title^3", "body"], "type": "best_fields"}}
                    ],
                    "filter": filters,
                }
            },
            "_source": ["content_type"],
        }
        data = self._call("POST", f"/{self.prefix}-*/_search", body) or {}
        hits = (data.get("hits") or {}).get("hits") or []
        return [
            SearchHit(index=h["_source"]["content_type"], id=str(h["_id"]), score=float(h.get("_score") or 0))
            for h in hits
        ]


def get_backend() -> Any:
    from django.utils.module_loading import import_string

    from university.core.providers import get_search_backend
    from university.core.providers.search import NullSearchBackend
    from university.search.conf import search_settings

    path = search_settings.get("BACKEND")
    if path:
        return import_string(path)(**(search_settings.get("BACKEND_OPTIONS") or {}))
    backend = get_search_backend()
    return DatabaseSearchBackend() if isinstance(backend, NullSearchBackend) else backend
