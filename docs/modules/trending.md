# university-trending

A configurable trending engine (spec §99). It depends only on `university-core` and is optional:
without it, social's trending feed uses its own simpler formula.

```bash
pip install university-trending
```

```python
INSTALLED_APPS += ["university.trending"]
```

Schedule `python manage.py compute_trending` (or the `compute_trending` task) every few minutes.

## Signals

Ids-only events become **hourly signal buckets** per item. No user ids are stored.

| Event | Item | Signal | Default weight |
| --- | --- | --- | --- |
| `content.viewed` (from analytics) | any | view | 0.2 |
| `social.post.reacted` | social post | reaction | 1 |
| `social.comment.created`, `anonymous.comment.created` | post | comment | 3 |
| `social.post.reposted` | original post | share | 5 |
| `events.registration.confirmed` | event | registration | 4 |
| `community.member.joined` | community | join | 3 |
| `marketplace.order.created` | listing | order | 4 |

Add your own in `TRENDING.SIGNALS` (`content_type` or `content_type_key`, `id_key`, `signal`).

## Scoring

The default `GravityVelocity` algorithm deliberately does **not** rank by total likes:

```
engagement = Σ weight[signal] × count            (within WINDOW_HOURS)
velocity   = recent rate / earlier rate           (last VELOCITY_HOURS vs. the rest), capped
score      = engagement × (1 + VELOCITY_WEIGHT × ln(1 + max(velocity − 1, 0)))
                        / (age_hours + 2) ^ GRAVITY
```

- **Engagement:** comments and shares outweigh views and likes, and the weights are configurable.
- **Velocity:** something rising now beats something that peaked yesterday.
- **Recency:** gravity decay by the item's age.
- **Breadth:** items need engagement from at least `MIN_UNIQUE_ACTORS` different people.

Replace the formula with `TRENDING.ALGORITHM`, a class with `score(stats)`.

### Anti-gaming

- A person's repeated signal on the same item counts **once** per `DEDUPE_HOURS` (spamming
  like/unlike does nothing).
- One account can't make an item trend (`MIN_UNIQUE_ACTORS`).
- Lists cap items per author (`MAX_PER_AUTHOR`).

## Reading trending

`GET /api/v1/trending/?type=social.post&scope_type=institution&scope_id=…&limit=20` returns
`[{content_type, object_id, score, title}]`.

- **Every item is checked for the viewer** with its content adapter: private communities,
  audience-only posts, blocked people, hidden and deleted content are skipped.
- **Scoped lists** (for example an institution's trending) use the item's audience.
- **Feeds:** social's `trending` feed (`RankedFeed`) asks Core's `content.trending_scores` hook
  for scores and ranks by them when this module is installed. Neither module imports the other.

## Settings

See [`TRENDING`](../configuration/index.md#trending-university-trending). Retention:
`trending.signals` (`SIGNAL_RETENTION_HOURS`, 168).
