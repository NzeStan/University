# university-notifications

In-app, email, push and SMS notifications. The module depends only on `university-core` and is
**event-driven**: other modules publish events containing ids only, and this module turns them
into notifications. Social, moderation, institution and community never import it, and it never
imports them.

```bash
pip install university-notifications
```

```python
INSTALLED_APPS += ["university.notifications"]
```

## What gets notified

| Event | Recipient | Verb | Category | Aggregates |
| --- | --- | --- | --- | --- |
| `social.mention.created` | mentioned person | `social.mention` | mentions | — |
| `social.comment.created` | post author / parent comment author | `social.comment` / `social.reply` | comments | per post / per comment |
| `social.post.reacted`, `social.comment.reacted` | author | `social.reaction`, `social.comment_reaction` | reactions | per post / comment |
| `social.post.reposted` | original author | `social.repost` | reposts | per post |
| `social.follow.created` / `.requested` / `.approved` | followee / followee / follower | `social.follow` … | follows | follows, requests |
| `moderation.action.taken` / `.reversed` | affected person | `moderation.<action>` / `moderation.reversed` | moderation | — |
| `moderation.appeal.decided` | appellant | `moderation.appeal_upheld` / `_overturned` | moderation | — |
| `institution.membership.verified` / `rejected` / `suspended` / `revoked` | member | `institution.membership_*` | account | — |
| `community.member.invited` | invitee | `community.invited` | communities | deduplicated |
| `community.member.joined` (approved by a manager) | member | `community.approved` | communities | deduplicated |
| `community.role.changed`, `.member.removed`, `.member.banned`, `.ownership.transferred` | member | `community.*` | communities | — |
| `events.registration.confirmed` / `waitlisted` / `promoted` / `declined` / `expired` | attendee | `events.*` | events | promotion and confirmation deduplicated |
| `events.attendee.notice` (`cancelled`, `rescheduled`, `reminder`) | each registrant | `events.cancelled` … | events | — |
| `creator.verification.*`, `creator.participation.changed`, `creator.deliverable.*` | creator or brand (whoever didn't act) | `creator.*` | creator | — |
| `marketplace.order.*`, `marketplace.dispute.resolved`, `marketplace.review.created` | the other party | `marketplace.*` | commerce | — |
| `payments.refund.succeeded`, `payments.payment.unfulfilled`, `payments.payout.*` | payer / payee | `payments.*` | commerce | — |
| `podcast.subscriber.notice`, `podcast.guest.added` | subscriber / guest | `podcast.*` | podcasts | new episodes grouped per show |
| `media.asset.failed` | uploader | `media.failed` | media | — |
| `security.login.suspicious`, `security.refresh_token.reused`, `user.password_changed`, `user.email_changed`, `security.mfa.*`, `security.api_key.created` | account owner | `security.*` | security | — |

Duplicates are suppressed. For example, if a comment mentions the post's author, they get the
mention but not a second "commented on your post" notification.

## Privacy and safety

- **No content copies.** A notification stores a verb, ids and enum values. Titles are rendered
  when read, from translatable text and the actor's *current* name. Renames and purges take
  effect immediately, and deleted content shows `target.available: false` instead of a stale
  excerpt.
- **Target labels are permission-checked.** `{target}` (for example a community name) is filled
  only when the viewer can see it, through Core's content adapters (institutions, communities and
  so on). After someone is removed from
  a private community, their notification reads "You were removed from a community."
- **Blocks.** Every actor notification passes Core's `users.can_interact(actor, recipient,
  "notify")` hook. When one person blocks another, the notifications between them are deleted.
  Mention policies are enforced by social before the event is published.
- **System notices never name an actor.** Moderation, security, institution and most community
  notices store no actor at all, so moderators stay anonymous to the people they moderate.
- **Anonymous content is never notified.** Routing a reply to an anonymous author would link them
  to their post. Moderation events about anonymous content carry no user id (moderation omits
  it), and appeal decisions include `appellant_id` only for non-anonymous content.
- **Suspended and banned people** still receive mandatory notices (moderation, security), so they
  learn what happened and how to appeal. Deleted accounts receive nothing.
- **Messages carry titles and links only.** Emails, pushes and SMS contain the rendered title and
  a link, never post bodies. Set `PUSH_PREVIEWS: False` to send a generic text to lock screens,
  which helps on shared phones.
- **Push tokens are credentials.** They are stored with a keyed hash for deduplication, never
  returned by the API, excluded from data exports, and hidden in the admin.

## Preferences

Preferences use Core's notification settings (`GET/PATCH /api/v1/me/notifications/`):

- master switches per channel (`in_app_enabled`, `email_enabled`, `push_enabled`, `sms_enabled`);
- per-category overrides: `"categories": {"reactions": {"push": false}, "security": {"sms": true}}`;
- quiet hours (`quiet_hours_start` / `quiet_hours_end`), evaluated in the person's own `timezone`
  and allowed to wrap past midnight;
- `digest_frequency`: `daily`, `weekly` or `never`.

Category defaults come from `NOTIFICATIONS.CATEGORIES`:

| Category | In-app | Email | Push | Notes |
| --- | --- | --- | --- | --- |
| security | always | — (Core already emails) | ✓ | mandatory; bypasses quiet hours |
| moderation | always | immediate | ✓ | mandatory |
| account, communities, events, creator, commerce | ✓ | immediate | ✓ | |
| mentions, comments, follows, reposts | ✓ | digest | ✓ | |
| reactions | ✓ | digest | — | |

SMS is off everywhere by default. People can opt in per category; SMS needs a verified phone and
costs money. `GET /api/v1/notifications/categories/` returns each category's defaults alongside
the caller's effective setting, ready for a settings screen.

## Delivery

```
event → handler → notify() ──► Notification (in-app)
                          └──► Delivery per channel ─► task: deliver() ─► channel ─► provider
                                                 └─► digest queue ─► send_digests()
```

- **Exactly-once claims.** A delivery moves from `pending` to `sending` with a conditional update,
  so duplicate task messages from at-least-once queues never send twice.
- **Retries** use exponential backoff (`RETRY_BASE_SECONDS × 2ⁿ`) up to `MAX_DELIVERY_ATTEMPTS`,
  then the delivery is marked `failed` with a reason code.
- **Skipped** if the notification was already read, the person is unreachable (no verified email
  or phone, no active device), or the channel is disabled.
- **Suppressed** during quiet hours (push and SMS) or beyond `PUSH_MAX_PER_HOUR`.
- **Digests.** Schedule `python manage.py send_notification_digests --frequency daily` (and
  `weekly`) with cron or Celery beat. Items read in the meantime are left out.
- **Aggregated** notifications deliver once, when first created, and later activity only updates
  the in-app row. Read notifications start a new row on new activity.

### Channels and providers

| Channel | Provider | Available when |
| --- | --- | --- |
| email | Core's email provider (SMTP, Anymail: SendGrid, Mailgun, SES, Brevo …) | verified email |
| push | `NOTIFICATIONS.PUSH_PROVIDER`: `NullPushProvider` (default), `FCMPushProvider` (HTTP v1, Android, iOS and web), `ExpoPushProvider` | an active device seen in the last `DEVICE_STALE_DAYS` |
| sms | Core's SMS provider (Termii, Africa's Talking, Twilio) | verified phone |

```python
UNIVERSITY = {
    "NOTIFICATIONS": {
        "PUSH_PROVIDER": "university.notifications.push.FCMPushProvider",
        "PUSH_PROVIDER_OPTIONS": {
            "project_id": "my-campus-app",
            "credentials_file": os.environ["FCM_CREDENTIALS_FILE"],  # never commit it
        },
        "OPEN_URL": "https://app.example.edu/notifications/{id}",
    }
}
```

Providers report unregistered tokens, and those devices are disabled automatically. To add
another channel (WhatsApp, for example), subclass `channels.BaseChannel` and register it in
`NOTIFICATIONS.CHANNELS`; producers don't change. Set a channel to `None` to disable it.

## Extending

```python
from django.utils.translation import gettext_lazy as _
from university.notifications.services import notify
from university.notifications.verbs import Verb, register_verb

register_verb(
    Verb(
        "events.reminder", "events", _("{target} starts in an hour"), show_actor=False, target_fallback=_("Your event")
    )
)

notify(recipient=user, verb="events.reminder", target_type="events.event", target_id=event.pk)
```

`notify()` applies every rule above: disabled verbs, reachability, self, blocks, preferences,
aggregation via `group_key`, and delivery planning. Disable built-in verbs with
`NOTIFICATIONS.DISABLED_VERBS`. Real-time gateways (WebSocket or SSE) can subscribe to
`notifications.notification.created` (ids only) or to the `notification_created` signal.

## API (`/api/v1/…`, authenticated)

| Method & path | Purpose |
| --- | --- |
| `GET notifications/?unread=&category=` | Cursor-paginated feed, newest activity first |
| `GET notifications/counts/` | `{unread, unseen}` for badges (capped at 1000) |
| `GET/DELETE notifications/{id}/` | One notification; delete it |
| `POST notifications/{id}/read/` · `unread/` | Read state |
| `POST notifications/read-all/` `{category?, before?}` | Mark read, optionally only up to what was displayed |
| `POST notifications/seen/` | Clear the "new" badge without reading |
| `GET notifications/categories/` | Categories, defaults and effective settings |
| `GET/POST notifications/devices/` | List and register push devices (`platform`, `token`, `name`) |
| `DELETE notifications/devices/{id}/` · `POST notifications/devices/unregister/` `{token}` | Unregister on sign-out |

Every query is scoped to the caller: another person's notification returns `404`. Registering
the same token from another account moves the device. Each person keeps at most
`MAX_DEVICES_PER_USER` active devices, and older ones are retired. Device registration is
throttled (`notifications_device_register`, 30/hour).

## Operations

- **Health check:** `notifications.deliveries` (non-critical) turns unhealthy when deliveries pile
  up unsent for more than an hour, usually because the task worker is down.
- **Retention policies:**

  | Policy | Removes | Default |
  | --- | --- | --- |
  | `notifications.read` | read notifications | 90 days |
  | `notifications.all` | all notifications | 365 days |
  | `notifications.deliveries` | delivery records | 30 days |
  | `notifications.disabled_devices` | disabled devices | 30 days |

- **Export and purge:** the export contains notification history (verbs, ids, timestamps) and
  devices without tokens. Purge deletes the person's notifications and devices and detaches them
  as an actor from other people's notifications.
- **`ASYNC_HANDLERS: True`** runs event handling on the task backend instead of in the request
  that published the event.
