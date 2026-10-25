# university-notifications

Notifications for the [University platform](https://github.com/NzeStan/University):
in-app, email, push (FCM, Expo) and SMS. Includes per-category preferences, quiet hours, digests,
aggregation and retries. This is an optional *level two* module that depends only on
`university-core`.

- **Event-driven.** Mentions, comments, replies, reactions, reposts, follows, moderation
  decisions, appeals, institution verification, community invitations and role changes, and
  security alerts become notifications. None of those modules imports this one.
- **Private by design.**
  - No content copies: titles are rendered when read, from the actor's current name.
  - Blocks are respected, and moderators' identities are never shown.
  - Nothing is sent about anonymous posts.
  - Push tokens are never returned by the API.
- **Aggregation.** "Ada and 4 more reacted to your post". Duplicate events are deduplicated.
- **Preferences.** Per-category and per-channel settings on top of Core's notification
  settings. Mandatory categories (security, moderation) always appear in-app. Quiet hours follow
  each person's own time zone.
- **Reliable delivery.** Each delivery is claimed atomically so it is never sent twice, retried
  with exponential backoff, capped per hour, and skipped once read. Daily or weekly email digests.
- **Africa-ready.** SMS goes through Core's Termii, Africa's Talking and Twilio providers, and
  push previews can be turned off for shared phones.

```bash
pip install university-notifications
```

```python
INSTALLED_APPS += ["university.notifications"]
```

See [the module documentation](../../docs/modules/notifications.md).
