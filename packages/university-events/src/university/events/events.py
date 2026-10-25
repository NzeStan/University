"""Event-bus names published by the events module (payloads carry ids only)."""

EVENT_CREATED = "events.event.created"
EVENT_UPDATED = "events.event.updated"
EVENT_PUBLISHED = "events.event.published"
EVENT_CANCELLED = "events.event.cancelled"
EVENT_RESCHEDULED = "events.event.rescheduled"
EVENT_HIDDEN = "events.event.hidden"

REGISTRATION_CONFIRMED = "events.registration.confirmed"
REGISTRATION_WAITLISTED = "events.registration.waitlisted"
REGISTRATION_PENDING_APPROVAL = "events.registration.pending_approval"
#: A paid ticket is held: a payments module creates a checkout and calls confirm_payment().
REGISTRATION_PAYMENT_REQUIRED = "events.registration.payment_required"
#: Moved from the waitlist into a seat (confirmed, or held for payment).
REGISTRATION_PROMOTED = "events.registration.promoted"
REGISTRATION_DECLINED = "events.registration.declined"
REGISTRATION_CANCELLED = "events.registration.cancelled"
REGISTRATION_EXPIRED = "events.registration.expired"
ATTENDEE_CHECKED_IN = "events.attendee.checked_in"
#: Fan-out per registrant: ``kind`` is cancelled, rescheduled or reminder.
ATTENDEE_NOTICE = "events.attendee.notice"
