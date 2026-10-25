# university-search

Permission-aware search across the platform (spec §42). It depends only on `university-core` and
implements Core's search abstraction (`university.core.providers.search`). Core never depends on
Elasticsearch or OpenSearch.

```bash
pip install university-search
python manage.py migrate
python manage.py search_reindex     # backfill existing content
```

## Backends

| Backend | Needs | Notes |
| --- | --- | --- |
| `DatabaseSearchBackend` (default) | nothing | **PostgreSQL full-text** (websearch queries, title weighted over body, ranked); token matching on other databases |
| `OpenSearchBackend` | OpenSearch or Elasticsearch 7+/8+ over HTTPS | API-key or basic auth; one index per content type (`<prefix>-<type>`) |

Choose with `SEARCH.BACKEND` (and `BACKEND_OPTIONS`), or Core's `PROVIDERS.SEARCH`. Any class
implementing `SearchBackend` (`index`, `delete`, `search`) works.

## Indexing

Content is indexed from ids-only events (`SEARCH.SOURCES`) through each module's **content
adapter**, so search never imports the content modules:

| Type | Indexed on | Removed on |
| --- | --- | --- |
| `social.post` / `social.comment` | created, updated, restored | deleted, hidden |
| `anonymous.post` | created | deleted (authors are never indexed) |
| `community.community` | created, updated | archived |
| `events.event` | published, updated, rescheduled | hidden, cancelled |
| `marketplace.listing` | published | hidden |
| `podcast.episode` | published | — |
| `creator.campaign` | published | closed, completed, cancelled, hidden |

Indexing runs on the task backend (`ASYNC_INDEXING`). `search_reindex [--type …]` backfills via
`ContentAdapter.iter_ids()`.

## Never leaking results

Each document carries a **visibility tag**:

- `public` if an anonymous visitor may see it;
- `<scope_type>:<scope_id>` if it's limited to an audience (institution, community …);
- `restricted` otherwise (drafts, moderation-hidden items). No viewer carries this tag.

At query time the viewer's tags (`public` plus their audiences) narrow the candidates, and then
**every hit is re-checked with its content adapter** for that viewer. Private communities,
audience-only posts, blocked people, and hidden or deleted content can't appear, even if the index
is stale. Titles and snippets are read fresh from the adapter.

## Enumeration protection (spec §90)

- Queries must be `MIN_QUERY_LENGTH`–`MAX_QUERY_LENGTH` characters. Invalid queries get one
  generic error, and results are capped at `MAX_RESULTS`.
- **People search** (`GET search/people/?q=`):
  - It matches handle prefixes and display names only. **Email addresses and phone numbers are
    never searchable**, and email-shaped queries return nothing.
  - Only `searchable` profiles appear: public ones, plus members-only profiles for signed-in
    users.
  - Blocks apply through Core's `can_view_profile`.
  - Queries need at least `PEOPLE_MIN_QUERY_LENGTH` (3) characters.
- Both endpoints are rate-limited (`search` 120/minute, `search_people` 30/minute).
- Anonymous content is never linked to an author in the index.

## API (`/api/v1/search/…`)

| Method & path | Returns |
| --- | --- |
| `GET ?q=&types=a,b&limit=` | `[{content_type, object_id, title, snippet, score}]` |
| `GET people/?q=` | `[{id, handle, display_name}]` |
| `GET types/` | indexable content types installed here |

## Operations

- **Purge:** a person's content is removed from the index (by author). Live content is re-indexed
  anonymised by its module.
- See [`SEARCH`](../configuration/index.md#search-university-search) for settings.
