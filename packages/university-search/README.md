# university-search

Permission-aware search for the [University platform](https://github.com/NzeStan/University).
This is an optional *level two* module that depends only on `university-core`, and it implements
Core's search abstraction.

- **Backends:** a database backend (PostgreSQL full-text with weighted ranking, or a portable
  fallback) and OpenSearch/Elasticsearch over HTTPS. Others plug in through Core's
  `SearchBackend` protocol.
- **Content** is indexed through ids-only events and content adapters: posts, comments,
  anonymous posts, communities, events, listings, episodes and campaigns. A `search_reindex`
  command backfills.
- **Every hit is re-checked for the viewer.** Visibility tags narrow the candidates, and the
  content adapter decides, so private communities, audience-only and hidden content, and blocked
  people never leak.
- **Enumeration-resistant** (spec section 90):
  - People search uses handles and display names only, never email or phone.
  - It respects `searchable` and profile privacy and blocks, needs longer queries, caps results
    and is rate-limited.
  - Anonymous content is never linked to anyone.

```bash
pip install university-search
```

See [the module documentation](../../docs/modules/search.md).
