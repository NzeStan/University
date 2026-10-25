# university-events

Events for the [University platform](https://github.com/NzeStan/University): lectures,
career fairs, hackathons, sports, worship, conferences. Covers discovery, registration, capacity,
FIFO waitlists, approvals, ticket types, schedules, venues, organizer teams and door check-in.
This is an optional *level two* module that depends only on `university-core`.

- **Hosted by anyone or any scope.** An event can be hosted by an institution or a community, and
  can be shown to its members only. Host-scope managers keep authority over it.
- **Overselling can't happen.**
  - Seats change under a row lock on the event.
  - Database check constraints guard capacity and ticket quantities.
  - A unique constraint prevents duplicate registrations.
- **Optional ticketing.** Free tickets work out of the box. Paid tickets hold a seat, and a
  payments module confirms them through ids-only events. Unpaid holds expire and pass the seat to
  the waitlist.
- **Secure check-in.** Ticket codes are HMAC-derived and only their keyed hash is stored, so a
  database leak can't mint tickets. Online links are revealed only to confirmed attendees.
- **Trust and safety.** Events opt in to moderation explicitly. Reports go to the host scope's
  moderators, and moderators can hide, restore or remove an event. Spam screening, blocks,
  content-creation restrictions, audit logging, export and purge are all included.
- **Calendar files** (`.ics`), reminders, and cancellation and reschedule notices (delivered by
  `university-notifications` when installed). Attendee CSV exports are protected against formula
  injection.

```bash
pip install university-events
```

```python
INSTALLED_APPS += ["university.events"]
```

See [the module documentation](../../docs/modules/events.md).
