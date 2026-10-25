# university-social

Posts, comments, reactions, reposts, polls, media, feeds and a **block-aware social graph** for
the [University platform](https://github.com/NzeStan/University). This is an optional
*level two* module that depends only on `university-core`.

- Posts with text, images, polls, hashtags, mentions and links. Edits keep a revision history.
- Visibility per post: `public`, `followers`, `private`, or an **audience** (`institution`,
  `campus`, `community`). Audience membership comes from whichever modules are installed,
  through Core's `scopes.memberships` hook, so social doesn't depend on them.
- Two-level comment threads, reactions, reposts and quotes, bookmarks.
- Follow (with optional approval), block, mute and restrict. Blocks are enforced server-side
  everywhere, including in other modules, through Core hooks.
- Pluggable feeds: home, explore, and trending ranked by engagement velocity.
- Anti-spam screening, rate limits, audited moderation scoped to the content's audience, data
  export, purge, and retention of unattached uploads.

```bash
pip install university-social
```

```python
INSTALLED_APPS = [..., *CORE_APPS, "university.social"]
```

Guide: https://github.com/NzeStan/University/blob/main/docs/modules/social.md
