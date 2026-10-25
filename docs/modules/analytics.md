# university-analytics

Privacy-conscious analytics: event ingestion and aggregation, active users, content views, and
platform and institution dashboards (spec §55). It depends only on `university-core`.

```bash
pip install university-analytics
```

```python
INSTALLED_APPS += ["university.analytics"]
```

## What is stored, and what isn't

The module subscribes to every platform event and keeps **daily counters** (`MetricDaily`):

| Kept | Never kept |
| --- | --- |
| date, metric name, scope (platform-wide, or e.g. `institution:<id>`), count | user ids, IP addresses, payloads, raw events, timestamps finer than a day |

- **Metrics** are event names matched by `TRACK` patterns (for example `social.post.created`,
  `events.registration.confirmed`, `marketplace.order.created`). `EXCLUDE` patterns win over
  `TRACK`.
- **Breakdowns** come from payload keys in `DIMENSIONS` (`institution_id`, `community_id`,
  `campus_id`) and from `scope_type`/`scope_id` pairs, so the same post counts platform-wide and
  for its institution.
- **Active users:** `active_users.daily`, `.weekly` and `.monthly` are counted once per person per
  period, using short-lived keyed hashes in the cache. Nothing is written to the database. Use a
  shared cache, such as Redis, in production.
- **Views:** `POST analytics/views/` `{content_type, object_id}` records a view only if the viewer
  may see the item (Core content adapters). It counts once per viewer per `VIEW_DEDUPE_HOURS` and
  stores no viewer. It feeds `views.<content_type>` and publishes `content.viewed` (ids only, no
  viewer) for trending. Unknown, hidden and nonexistent items all return the same 404.

## Dashboards

| Endpoint | Who | Notes |
| --- | --- | --- |
| `GET analytics/overview/?from=&to=&metrics=` | `analytics.view` (platform) | platform-wide series and totals |
| `GET analytics/scopes/{type}/{id}/?from=&to=&metrics=` | `analytics.view` at that scope | e.g. **institution analytics** for its leadership (`analytics_viewer` role on the institution) |
| `GET analytics/metrics/` | `analytics.view` | known metric names |

**Small-group suppression:** scope reports replace counts below `MIN_REPORTABLE` (default 5) with
`null`, so a handful of people can't be singled out. Platform totals aren't suppressed.

Creator analytics live in `university-creator` (each creator's own dashboard) and podcast listening
stats live in `university-podcast`. Both follow the same aggregate-only approach.

## Sinks (warehouses)

Spec §55 says not to keep every event in the primary database, so raw-event pipelines plug in as
**sinks** (`ANALYTICS.SINKS`). Each sink receives a minimised record:

```json
{"event": "social.post.created", "occurred_at": "2026-10-24T14:05:00+00:00",
 "dimensions": ["institution:…"], "actor": "3f9a…"}
```

`actor` is a keyed hash that **changes every month**: a warehouse can count uniques within a month
but can't identify anyone or follow them across months. Payloads are never forwarded. `LogSink`
writes JSON lines; implement `AnalyticsSink.emit()` for ClickHouse, BigQuery, Kafka and so on.

## Settings

See [`ANALYTICS`](../configuration/index.md#analytics-university-analytics). Throttle:
`analytics_view` (600/hour). Retention: `analytics.daily_metrics` (`RETENTION_DAYS`, 1095). Nothing
personal is stored, so there's nothing to export or purge.
