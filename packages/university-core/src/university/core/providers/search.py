"""Search backend abstraction.

Core defines the protocol only; real backends (PostgreSQL full-text,
OpenSearch, Elasticsearch …) ship in the optional ``university-search``
package. Modules index documents through this interface so that the search
engine can be swapped without touching them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SearchDocument:
    index: str
    id: str
    body: Mapping[str, Any]
    #: Opaque visibility tags evaluated at query time (e.g. "public",
    #: "institution:<uuid>"). Never index private data without tags.
    visibility: Sequence[str] = field(default_factory=lambda: ("public",))


@dataclass(frozen=True)
class SearchHit:
    index: str
    id: str
    score: float
    highlights: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchQuery:
    index: str
    text: str
    filters: Mapping[str, Any] = field(default_factory=dict)
    visibility: Sequence[str] = field(default_factory=lambda: ("public",))
    limit: int = 20
    offset: int = 0


class SearchBackend(Protocol):
    def index(self, documents: Iterable[SearchDocument]) -> None: ...

    def delete(self, index: str, ids: Iterable[str]) -> None: ...

    def search(self, query: SearchQuery) -> list[SearchHit]: ...


class NullSearchBackend:
    """Accepts documents and finds nothing. The default when search is absent."""

    def index(self, documents: Iterable[SearchDocument]) -> None:
        return None

    def delete(self, index: str, ids: Iterable[str]) -> None:
        return None

    def search(self, query: SearchQuery) -> list[SearchHit]:
        return []
