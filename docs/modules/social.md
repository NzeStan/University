# university-social

Posts, comments, reactions, reposts, polls, media, feeds and a block-aware social graph. It
depends only on `university-core`. Audience features (institution-only, campus-only and
community-only posts) work with whichever membership modules are installed, through Core's
`scopes.memberships` hook.

```bash
pip install university-social
```

```python
INSTALLED_APPS += ["university.social"]
```

## Visibility, the core guarantee

Every list (feeds, timelines, hashtags, bookmarks, comments) is built from one selector,
`visible_posts(viewer)`. Single-object checks use `can_view_post(viewer, post)`, which applies the
same rules in Python, and the test suite checks that the two agree across every combination of
visibility, status and viewer.

| Visibility | Who can see it |
| --- | --- |
| `public` | Everyone. Exceptions: an author whose *profile* is members-only shows it to signed-in users only; an author whose profile is private shows it to followers only |
| `followers` | Approved followers |
| `private` | The author only |
| `institution` / `campus` / `community` | Members of that audience (`audience_id`), as reported by membership modules |

These rules always apply, whatever the visibility:

- deleted posts, posts by authors who aren't active (suspended, banned, deleted) and posts that
  aren't published are invisible to everyone except the author;
- users who block each other (in either direction) can't see each other's content;
- anything invisible returns **404**, including when someone tries to react, comment or bookmark,
  so the API never reveals that a hidden post exists.

Authors can only post to audiences they belong to. A verified institution member, for example,
can post to their institution; a pending member can't.

## Social graph

| Action | Effect |
| --- | --- |
| Follow | Active immediately, or `pending` when the target has `requires_follow_approval` (a protected account). Protected accounts hide their follower lists from non-followers. |
| Block | Severs follows in both directions (and corrects the counters), hides content and profiles both ways (including Core's `/users/{id}/`), prevents follows, comments and mentions. Enforced server-side through the `users.can_view_profile` and `users.can_interact` hooks, so future modules (messaging, events …) respect blocks automatically. |
| Mute | Removes the muted user from home, explore, hashtag and audience feeds; their profile timeline stays reachable. |
| Restrict | The restricted user's comments on your posts are visible only to the two of you. They aren't told. |

Mention policy (`allow_mentions_from`: everyone, people I follow, nobody): mentions that aren't
allowed are dropped silently.

## Content features

- **Posts**: text up to 5,000 characters; Unicode hashtags (so Yorùbá, Hausa, Igbo and Swahili
  tags work); mentions; links (recorded, never fetched, so the server can't be used for SSRF);
  optional location (off by default); and a comments switch.
- **Editing**: allowed within `EDIT_WINDOW_MINUTES`. The previous text is kept in `PostRevision`
  for accountability, and hashtags and mentions are re-parsed. Only newly mentioned users are
  notified.
- **Reposts and quotes**: only **public** posts can be reposted, so followers-only content can't
  leak. Reposting a repost targets the original. Each user gets one pure repost per post (enforced
  by a database constraint). If the original becomes invisible, the repost shows
  `{"unavailable": true}`.
- **Comments**: two-level threads (replies to replies attach to the top-level comment). Authors,
  the post's author and moderators can delete comments.
- **Reactions**: configurable types (`like`, `love`, `laugh`, `wow`, `sad`, `angry`, `support`),
  one per user per item, switchable, idempotent and race-safe.
- **Polls**: 2–4 options, single or multiple choice, an optional duration, and a database
  constraint against double voting.
- **Media**: images are checked by content signature (SVG and HTML are rejected, and the extension
  must match the content), stored under random names, and stay owned by the uploader until
  attached to one of *their* posts. Unattached uploads are purged after 24 hours.
- **Bookmarks**: private to the user. Bookmarked posts that later become invisible drop out of the
  list.

## Feeds

| Feed | Provider | Notes |
| --- | --- | --- |
| `home` | `HomeFeed` | You, the people you follow, and your audiences (`HOME_INCLUDES_MEMBER_SCOPES`); cursor-paginated; signed-in users only |
| `explore` | `ExploreFeed` | Public posts, newest first |
| `trending` | `RankedFeed` | Recent public posts ranked by **engagement velocity**: `(w_r·reactions + w_c·comments + w_p·reposts + 1) / (age_hours + 2)^gravity`. Uses `?offset=&limit=`. |

Feeds are pluggable: `UNIVERSITY["SOCIAL"]["FEEDS"] = {"campus": "myapp.feeds.CampusFeed"}`.
Subclass `FeedProvider` and start from `visible_posts(viewer)` so every privacy rule still applies.
A test caps the number of queries per page, so feed cost doesn't grow with page size (no N+1).

## Moderation and safety

- **Anti-spam**: every post and comment goes through `PROVIDERS.SPAM`. *Reject* refuses the
  content with `400 content_rejected`. *Review* publishes it as `pending_review`, visible only to
  the author until a moderator approves it.
- **Moderators** hold `social.content.moderate`, either platform-wide (`social_moderator` role) or
  **at the content's audience scope**. Institution moderators, for example, can moderate only
  posts restricted to their institution. Hide, restore and remove actions are audited.
- **Rate limits** are enforced in the services: `social_post` 30/hour, `social_comment` 120/hour,
  `social_reaction` 600/hour, `social_follow` 200/day, `social_media_upload` 60/hour.

## Privacy integration

- **Profile**: `users.public_profile` adds bio, counters and, for signed-in viewers, the
  relationship (`following`: active, pending or none; `followed_by`).
- **Export**: posts, comments, follows, blocks, mutes, restrictions and bookmarks.
- **Purge**: hard-deletes the user's posts, comments, media and reactions, removes graph edges, and
  recomputes counters on other users' posts and profiles.
- **Deletion**: a soft-deleted account's content disappears immediately because authors must be
  active.

## API (`/api/v1/social/…`)

| Method & path | Description |
| --- | --- |
| `POST posts/` | Create (`body`, `visibility`, `audience_id`, `media[]`, `poll`, `comments_enabled`) |
| `GET/PATCH/DELETE posts/{id}/` | Read; edit (author); delete (author or moderator) |
| `POST/DELETE posts/{id}/reaction/` | React `{kind}` / remove |
| `POST/DELETE posts/{id}/repost/` | Repost or quote (`{body}`) / undo |
| `POST/DELETE posts/{id}/bookmark/` | Bookmark / remove |
| `POST posts/{id}/poll/vote/` | `{options: [...]}` |
| `GET/POST posts/{id}/comments/?parent=` | Thread / comment (`{body, parent}`) |
| `PATCH/DELETE comments/{id}/` · `POST/DELETE comments/{id}/reaction/` | |
| `POST posts/{id}/hide\|restore/` · `POST comments/{id}/hide\|restore/` | Moderation |
| `GET feeds/{home\|explore\|trending}/` | Feeds |
| `GET users/{id}/posts/` · `hashtags/{tag}/posts/` · `audiences/{type}/{id}/posts/` | Timelines |
| `GET hashtags/?q=` | Hashtag search |
| `POST media/` (multipart) · `DELETE media/{id}/` | Uploads |
| `POST/DELETE users/{id}/follow\|block\|mute\|restrict/` | Graph |
| `GET users/{id}/followers/` · `following/` | Lists (respect protection and blocks) |
| `GET/PATCH me/profile/` · `GET me/bookmarks/` | |
| `GET me/follow-requests/` · `POST me/follow-requests/{id}/approve\|decline/` | |
| `DELETE me/followers/{user_id}/` · `GET me/blocks\|mutes\|restrictions/` | |

## Events

`social.post.created|updated|deleted|reposted|reacted|hidden|restored`,
`social.comment.created|deleted|reacted|hidden`, `social.mention.created`,
`social.follow.created|requested|approved|removed`, `social.block.created` and
`social.poll.voted`. Payloads contain ids only, never post text. The notifications, search and
trending modules consume these.
