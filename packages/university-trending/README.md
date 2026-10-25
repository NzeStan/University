# university-trending

A configurable trending engine for the [University platform](https://github.com/NzeStan/University).
This is an optional *level two* module that depends only on `university-core`.

- **Signals:** views, reactions, comments, shares, event registrations, community joins and
  marketplace orders, taken from ids-only events and kept as hourly buckets with no user ids.
- **Scoring** combines weighted engagement, velocity (rising now versus earlier) and recency
  (gravity decay). It never ranks by total likes, and the weights, window, gravity and velocity are
  all configurable. The algorithm itself can be swapped.
- **Anti-gaming:** each person counts once per signal per item per window, items need a minimum
  number of distinct people, and lists cap items per author.
- **Permission-aware:** every listed item is checked against the viewer (privacy, blocks,
  audiences, moderation). There are trending lists per type and per scope (for example an
  institution).
- **Feeds:** social's ranked "trending" feed uses these scores automatically, through Core's
  `content.trending_scores` hook.

```bash
pip install university-trending
```

See [the module documentation](../../docs/modules/trending.md).
