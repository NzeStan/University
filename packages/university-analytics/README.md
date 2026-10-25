# university-analytics

Privacy-conscious analytics for the [University platform](https://github.com/NzeStan/University):
event aggregation, active users, content views, and platform and institution dashboards. This is an
optional *level two* module that depends only on `university-core`.

- **Aggregates only.** Ids-only platform events become daily counters, platform-wide and per scope
  (institution, community …). There are no raw events, user ids or payloads.
- **Active users** (daily, weekly, monthly) are counted with short-lived keyed hashes, never
  stored.
- **Views** of any content (posts, events, episodes, listings …) are recorded only if the viewer
  may see the item, once per window, without storing who viewed.
- **Small-group suppression** on scope dashboards stops individuals being singled out.
- **Sinks** forward minimised, pseudonymised events (rotating monthly) to warehouses such as
  ClickHouse or BigQuery.

```bash
pip install university-analytics
```

See [the module documentation](../../docs/modules/analytics.md).
