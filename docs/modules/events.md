# university-events

Events for campuses and communities: discovery, registration, capacity, waitlists, approvals,
tickets, schedules, venues, organizer teams and check-in. It depends only on `university-core`.
Ticketing is free by default; paid tickets are optional and go through a payments module.

```bash
pip install university-events
```

```python
INSTALLED_APPS += ["university.events"]
```

## Hosting

| Host | Requirement |
| --- | --- |
| A person | A verified email (`CREATION_POLICY: "verified_users"`), or `events.create` under `"permission"`. At most `MAX_UPCOMING_EVENTS_PER_USER` upcoming events. |
| A scope (`host_type`/`host_id`: institution, campus, community …) | `events.manage` at that scope: the `events_manager` role, or community owners and admins (granted by `COMMUNITY.ROLE_PERMISSIONS`). |

The host scope is the event's **permission parent**. Its managers manage the event, and its
moderators handle reports about it. Events start as **drafts**. Publishing checks that the start
is in the future, that in-person events have a venue or location details, and that online events
have an `https://` link.

| Visibility | Who sees it | Listed in discovery |
| --- | --- | --- |
| `public` | everyone | yes |
| `unlisted` | anyone with the link | no |
| `audience` | members of the host scope (via Core's `scopes.memberships`); registrants keep access after leaving | to members |

Drafts and moderation-hidden events are visible to organizers and managers only. Cancelled events
stay visible, so attendees see the cancellation.

### Organizers

| Role | Can |
| --- | --- |
| `owner` (exactly one, enforced by the database) | everything; transfers ownership |
| `organizer` | edit the event, tickets, sessions and registrations; add check-in staff |
| `checkin` | check attendees in and see the attendee list; not public |

People only grant roles below their own. Owners transfer ownership before leaving. Host-scope
managers and platform staff act with owner rank. Roles become permissions at the event's scope
through Core's `permissions.implicit_grants` hook (`events.manage`, `events.checkin`).

## Registration

```
register ─► requires_approval? ── yes ─► pending_approval ─► approve ─┐
                │ no                                                  │
                ▼                                                     ▼
        seat available? ── yes ─► free ticket: confirmed     paid: pending_payment (held)
                │ no                                                  │ confirm_payment()
                ▼                                                     ▼
        waitlist on? ── yes ─► waitlisted (FIFO) ─► promoted when a seat frees   confirmed
                │ no
                ▼
             409 event_full
```

- **No overselling.** Seats change under a row lock on the event. Database check constraints
  stop `seats_taken` from exceeding `capacity` and ticket sales from exceeding `quantity`. A unique
  constraint makes duplicate registrations impossible, and registering twice returns the existing
  registration.
- **Waitlists** are first in, first out. When a seat frees up (cancellation, decline, expired
  hold, a capacity increase, purge), the next person whose ticket type still has room is seated.
  `WAITLIST_AUTO_PROMOTE` controls this.
- **Windows.** Registration is open between `registration_opens_at` and `registration_closes_at`
  (default: the start). Attendees can cancel until the event ends, unless they have checked in.
- **Approval.** Organizers approve (seating or waitlisting the person) or decline. Declined people
  can't re-register.
- **Blocks.** If the attendee and the event's creator have blocked each other (Core's
  `users.can_interact` hook), the event looks nonexistent.

### Tickets and payments

Ticket types have a name, a price in minor units (kobo, pesewas, cents), a currency, an optional
quantity and an optional sales window. With several active types, the attendee chooses one. Prices
lock once tickets are sold, and types with sales are deactivated instead of deleted.

Paid tickets are off until `PAID_TICKETS_ENABLED: True`. They're sold as the
`events.registration` **payable** (Core's contract), so any payments module can take the money,
typically `university-payments`:

1. Registering for a paid ticket holds a seat (`pending_payment`, for `PAYMENT_HOLD_MINUTES`).
2. The attendee pays with `POST payments/checkout/` `{"purpose": "events.registration",
   "object_id": <registration>}`. Only the registrant can pay, and the checkout expires with the
   hold.
3. A verified payment confirms the ticket through `confirm_payment` (idempotent per reference).
   If the hold already expired, the payment is refunded automatically.
4. `release_expired_holds()` (task or `manage.py release_event_holds`) passes unpaid seats to the
   waitlist.
5. **Refunds:** declined attendees and cancelled events are refunded in full. Attendees who cancel
   are refunded until `REFUND_CUTOFF_HOURS` before the start (`REFUND_ON_ATTENDEE_CANCEL`). A
   full refund by finance cancels the ticket and frees the seat.

### Check-in

Each confirmed attendee has a **ticket code** (`XXXXX-XXXXX-XXXXX-XXXXX`, shown as a QR code by
clients) in `GET events/{id}/registration/`. The code is an HMAC of the registration id, so it's
never stored. Only a keyed hash is kept for lookup, which means a database leak can't produce valid
tickets. Codes survive key rotation (`SECURITY.HMAC_KEY_FALLBACKS`). Check-in staff post the code
(case, spaces and dashes are ignored). Codes from cancelled, declined or expired registrations are
rejected (`ticket_not_valid`), and duplicates return `already_checked_in` with the time.

### Online events

`online_url` is returned **only to confirmed attendees and organizers**: in event details, in
their registration, and in their calendar file. Waitlisted or pending people and the public never
see it.

## Schedules, venues and calendars

- **Sessions** (`events/{id}/sessions/`): title, time within the event, location and speakers
  (names and titles; speakers don't need accounts).
- **Venues** (`venues/`): reusable places with address, coordinates, capacity and accessibility
  notes. They are owned by a person or by a scope (managed with `events.manage` there).
- **Calendar**: `GET events/{id}/calendar.ics` returns an RFC 5545 file with escaping and line
  folding, `STATUS:CANCELLED` once cancelled, and an increasing `SEQUENCE`, so calendar apps update
  the entry.
- **Cover images**: uploads are checked by content signature (JPEG, PNG, WebP), size limited and
  stored under random names.

## Notices and notifications

The module publishes ids-only events. With `university-notifications` installed, attendees are
notified:

| Event | Notification |
| --- | --- |
| `events.registration.confirmed` | "You're registered for {event}." |
| `events.registration.waitlisted` | "You're on the waitlist for {event}." |
| `events.registration.promoted` | "A spot opened up …" (or "… complete payment to keep it"), once, without a duplicate "registered" |
| `events.registration.declined` / `.expired` | declined / held ticket expired |
| `events.attendee.notice` (`cancelled`, `rescheduled`, `reminder`) | sent to every registrant |

Changing a published event's time, venue, format or location sends `rescheduled` notices and
re-arms reminders. Schedule `python manage.py send_event_reminders` hourly; each reminder is
claimed atomically, so overlapping runs never send twice.

## Trust and safety

Events **opt in to moderation** (`moderatable = True`) with this explicit policy:

- **Who investigates.** The event's host scope (community or institution moderators); otherwise
  platform moderators.
- **Actions.**
  - `hide`: organizers only; the event can't be published or registered for.
  - `restore`.
  - `remove`: cancels the event, notifies attendees, then soft-deletes it.
- **User-level sanctions** (warn, restrict and so on) apply to the event's creator under
  moderation's usual rules. Organizers can't moderate their own events.

Spam screening covers titles, descriptions and venues, and content-creation restrictions apply
(`events.event`). Every management action is audited.

## API (`/api/v1/…`)

| Method & path | Who |
| --- | --- |
| `GET events/?q=&category=&format=&from=&to=&scope_type=&scope_id=&city=&country=&free=` | anyone (audience events for members) |
| `POST events/` | hosts |
| `GET events/by-slug/{slug}/` · `GET/PATCH/DELETE events/{id}/` | viewers / managers (DELETE: drafts without registrations) |
| `POST events/{id}/publish/` · `cancel/` · `POST/DELETE events/{id}/cover/` | managers |
| `GET events/{id}/calendar.ics` | viewers |
| `GET/POST events/{id}/ticket-types/` · `PATCH/DELETE …/{ticket_type_id}/` | viewers / managers |
| `GET/POST events/{id}/sessions/` · `PATCH/DELETE …/{session_id}/` | viewers / managers |
| `GET/POST events/{id}/organizers/` · `DELETE …/{user_id}/` · `POST events/{id}/transfer-ownership/` | viewers / managers |
| `POST events/{id}/register/` `{ticket_type?, share_contact?}` · `GET/DELETE events/{id}/registration/` | attendees |
| `GET events/{id}/registrations/?status=&checked_in=` | organizers and check-in staff |
| `GET events/{id}/registrations/export.csv` | managers (formula-injection safe; emails only when the attendee chose `share_contact`) |
| `POST events/{id}/registrations/{rid}/approve/` · `decline/` | managers |
| `POST events/{id}/check-in/` `{code}` | check-in staff |
| `GET me/event-registrations/?upcoming=` · `GET me/events/` | users |
| `GET/POST venues/` · `GET/PATCH venues/{id}/` | anyone / owners and scope managers |

Throttles: `events_create` (10/day), `events_venue_create` (20/day), `events_register`
(30/hour), `events_checkin` (1200/hour).

## Operations

- **Export:** registrations and organizer roles.
- **Purge:** deletes the person's registrations (their seats go to the waitlist) and organizer
  roles, and detaches them from events, venues and check-ins. Hosted events remain for attendees
  and scope managers.
- **Retention:** `events.past_registrations` removes attendance history
  `REGISTRATION_RETENTION_DAYS` (730) after an event ends.
- **Scheduled jobs:** `send_event_reminders` (hourly) and `release_event_holds` (every few
  minutes, when paid tickets are on). Both are also available as tasks.
