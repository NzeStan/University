"""Notification verbs: what a notification *says*, registered once per kind.

A verb maps a key to a category and translatable text. Text is rendered when
read (``{actor}``, ``{others}``, ``{target}`` and allow-listed ``data`` keys),
so notifications never hold copies of content::

    from university.notifications.verbs import Verb, register_verb

    register_verb(Verb("events.reminder", "events", _("{target} starts in an hour"),
                       show_actor=False, target_fallback=_("Your event")))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class Verb:
    key: str
    category: str
    text: Any
    #: Used when several actors aggregated: ``{others}`` is the extra count.
    aggregate_text: Any = None
    #: False for system notices (moderation, security): the actor is never stored or shown.
    show_actor: bool = True
    #: Shown for ``{target}`` when the recipient can't see the target (or there is none).
    target_fallback: Any = None
    #: ``data`` keys that may appear in the text (enum values only).
    text_data: tuple[str, ...] = field(default_factory=tuple)

    @property
    def aggregates(self) -> bool:
        return self.aggregate_text is not None


_VERBS: dict[str, Verb] = {}


def register_verb(verb: Verb, *, replace: bool = False) -> Verb:
    if verb.key in _VERBS and not replace and _VERBS[verb.key] != verb:
        raise ImproperlyConfigured(f"Notification verb {verb.key!r} is already registered.")
    _VERBS[verb.key] = verb
    return verb


def get_verb(key: str) -> Verb:
    try:
        return _VERBS[key]
    except KeyError:
        raise ImproperlyConfigured(f"Unknown notification verb {key!r}.") from None


def has_verb(key: str) -> bool:
    return key in _VERBS


def all_verbs() -> list[Verb]:
    return sorted(_VERBS.values(), key=lambda v: v.key)


def _system(key: str, category: str, text: Any, **kwargs: Any) -> Verb:
    return register_verb(Verb(key, category, text, show_actor=False, **kwargs))


A_COMMUNITY = _("a community")
YOUR_INSTITUTION = _("your institution")

# ------------------------------------------------------------------ social
register_verb(Verb("social.mention", "mentions", _("{actor} mentioned you")))
register_verb(
    Verb(
        "social.comment",
        "comments",
        _("{actor} commented on your post"),
        aggregate_text=_("{actor} and {others} more commented on your post"),
    )
)
register_verb(
    Verb(
        "social.reply",
        "comments",
        _("{actor} replied to your comment"),
        aggregate_text=_("{actor} and {others} more replied to your comment"),
    )
)
register_verb(
    Verb(
        "social.reaction",
        "reactions",
        _("{actor} reacted to your post"),
        aggregate_text=_("{actor} and {others} more reacted to your post"),
    )
)
register_verb(
    Verb(
        "social.comment_reaction",
        "reactions",
        _("{actor} reacted to your comment"),
        aggregate_text=_("{actor} and {others} more reacted to your comment"),
    )
)
register_verb(
    Verb(
        "social.repost",
        "reposts",
        _("{actor} reposted your post"),
        aggregate_text=_("{actor} and {others} more reposted your post"),
    )
)
register_verb(
    Verb(
        "social.follow",
        "follows",
        _("{actor} started following you"),
        aggregate_text=_("{actor} and {others} more started following you"),
    )
)
register_verb(
    Verb(
        "social.follow_request",
        "follows",
        _("{actor} requested to follow you"),
        aggregate_text=_("{actor} and {others} more requested to follow you"),
    )
)
register_verb(Verb("social.follow_approved", "follows", _("{actor} accepted your follow request")))

# -------------------------------------------------------------- moderation
_system("moderation.warn", "moderation", _("You received a warning from the moderators."))
_system("moderation.hide", "moderation", _("Some of your content was hidden by the moderators."))
_system("moderation.remove", "moderation", _("Some of your content was removed by the moderators."))
_system("moderation.restore", "moderation", _("Your content was restored."))
# Inbox messages are anonymous: the notification never names (or hints at) the sender.
_system("anonymous.message_received", "inbox", _("You have a new anonymous message."))
_system(
    "institution.announcement",
    "announcements",
    _("New announcement: {target}"),
    target_fallback=_("from your institution"),
)
register_verb(Verb("opportunities.application", "opportunities", _("{actor} applied to {target}")))
register_verb(Verb("messaging.message", "messages", _("{actor} sent you a message")))
register_verb(Verb("messaging.request", "messages", _("{actor} wants to send you a message")))
_system(
    "opportunities.shortlisted",
    "opportunities",
    _("You were shortlisted for {target}"),
    target_fallback=_("an opportunity"),
)
_system(
    "opportunities.hired",
    "opportunities",
    _("Good news: you were selected for {target}"),
    target_fallback=_("an opportunity"),
)
_system(
    "opportunities.rejected",
    "opportunities",
    _("An update on your application for {target}"),
    target_fallback=_("an opportunity"),
)
_system(
    "institution.announcement_urgent",
    "urgent_announcements",
    _("Urgent announcement: {target}"),
    target_fallback=_("from your institution"),
)
_system("promotions.approved", "promotions", _("Your campaign was approved and is running."))
_system("promotions.rejected", "promotions", _("Your campaign wasn't approved."))
_system("promotions.completed", "promotions", _("Your campaign has finished."))
_system("subscriptions.activated", "commerce", _("Your premium plan is active. Enjoy!"))
_system("subscriptions.renewal_due", "commerce", _("Your premium plan ends soon. Renew to keep it."))
_system("subscriptions.expired", "commerce", _("Your premium plan has ended."))
_system("moderation.restrict", "moderation", _("Your account was restricted by the moderators."))
_system("moderation.suspend", "moderation", _("Your account was suspended by the moderators."))
_system("moderation.ban", "moderation", _("Your account was banned by the moderators."))
_system("moderation.reversed", "moderation", _("A moderation decision affecting you was reversed."))
_system("moderation.appeal_upheld", "moderation", _("Your appeal was reviewed and the decision stands."))
_system("moderation.appeal_overturned", "moderation", _("Your appeal was successful and the decision was reversed."))

# ------------------------------------------------------------- institution
_system(
    "institution.membership_verified",
    "account",
    _("Your membership of {target} was verified."),
    target_fallback=YOUR_INSTITUTION,
)
_system(
    "institution.membership_rejected",
    "account",
    _("Your membership request for {target} was declined."),
    target_fallback=YOUR_INSTITUTION,
)
_system(
    "institution.membership_suspended",
    "account",
    _("Your membership of {target} was suspended."),
    target_fallback=YOUR_INSTITUTION,
)
_system(
    "institution.membership_revoked",
    "account",
    _("Your membership of {target} was revoked."),
    target_fallback=YOUR_INSTITUTION,
)

# --------------------------------------------------------------- community
register_verb(
    Verb("community.invited", "communities", _("{actor} invited you to join {target}"), target_fallback=A_COMMUNITY)
)
register_verb(
    Verb(
        "community.ownership",
        "communities",
        _("{actor} made you the owner of {target}"),
        target_fallback=A_COMMUNITY,
    )
)
_system(
    "community.approved", "communities", _("Your request to join {target} was approved."), target_fallback=A_COMMUNITY
)
_system(
    "community.role_changed",
    "communities",
    _("Your role in {target} is now {role}."),
    target_fallback=A_COMMUNITY,
    text_data=("role",),
)
_system("community.removed", "communities", _("You were removed from {target}."), target_fallback=A_COMMUNITY)
_system("community.banned", "communities", _("You were banned from {target}."), target_fallback=A_COMMUNITY)

# ------------------------------------------------------------------ events
AN_EVENT = _("an event")
_system("events.registered", "events", _("You're registered for {target}."), target_fallback=AN_EVENT)
_system("events.waitlisted", "events", _("You're on the waitlist for {target}."), target_fallback=AN_EVENT)
_system(
    "events.promoted", "events", _("A spot opened up: you're now registered for {target}."), target_fallback=AN_EVENT
)
_system(
    "events.promoted_payment",
    "events",
    _("A spot opened up for {target}. Complete payment to keep it."),
    target_fallback=AN_EVENT,
)
_system("events.declined", "events", _("Your registration for {target} was declined."), target_fallback=AN_EVENT)
_system("events.hold_expired", "events", _("Your held ticket for {target} expired."), target_fallback=AN_EVENT)
_system("events.cancelled", "events", _("{target} was cancelled."), target_fallback=_("An event you registered for"))
_system(
    "events.rescheduled",
    "events",
    _("{target} has a new date, time or place."),
    target_fallback=_("An event you registered for"),
)
_system("events.reminder", "events", _("{target} starts soon."), target_fallback=_("An event you registered for"))

# ----------------------------------------------------------------- creator
A_CAMPAIGN = _("a campaign")
_system("creator.verified", "creator", _("Your creator profile is now verified."))
_system("creator.verification_declined", "creator", _("Your creator verification request was declined."))
_system("creator.verification_revoked", "creator", _("Your creator verification was removed."))
_system("creator.invited", "creator", _("You've been invited to the campaign {target}."), target_fallback=A_CAMPAIGN)
_system("creator.applied", "creator", _("A creator applied to {target}."), target_fallback=A_CAMPAIGN)
_system("creator.shortlisted", "creator", _("You've been shortlisted for {target}."), target_fallback=A_CAMPAIGN)
_system("creator.accepted", "creator", _("You're in! You've been accepted for {target}."), target_fallback=A_CAMPAIGN)
_system(
    "creator.invitation_accepted",
    "creator",
    _("A creator accepted your invitation to {target}."),
    target_fallback=A_CAMPAIGN,
)
_system("creator.declined", "creator", _("Your participation in {target} was declined."), target_fallback=A_CAMPAIGN)
_system("creator.withdrawn", "creator", _("A creator withdrew from {target}."), target_fallback=A_CAMPAIGN)
_system("creator.cancelled", "creator", _("A collaboration on {target} was cancelled."), target_fallback=A_CAMPAIGN)
_system("creator.completed", "creator", _("Your collaboration on {target} is complete."), target_fallback=A_CAMPAIGN)
_system(
    "creator.deliverable_submitted",
    "creator",
    _("A deliverable was submitted for {target}."),
    target_fallback=A_CAMPAIGN,
)
_system(
    "creator.deliverable_approved",
    "creator",
    _("Your deliverable for {target} was approved."),
    target_fallback=A_CAMPAIGN,
)
_system(
    "creator.deliverable_changes",
    "creator",
    _("Changes were requested on your deliverable for {target}."),
    target_fallback=A_CAMPAIGN,
)

# ---------------------------------------------------------------- commerce
YOUR_ITEM = _("your item")
_system("marketplace.order_placed", "commerce", _("New order for {target}."), target_fallback=YOUR_ITEM)
_system(
    "marketplace.order_paid",
    "commerce",
    _("An order for {target} was paid. Time to fulfil it."),
    target_fallback=YOUR_ITEM,
)
_system(
    "marketplace.order_fulfilled",
    "commerce",
    _("Your order of {target} is on its way or ready for pickup."),
    target_fallback=_("an item"),
)
_system("marketplace.order_completed", "commerce", _("An order for {target} was completed."), target_fallback=YOUR_ITEM)
_system(
    "marketplace.order_cancelled", "commerce", _("An order for {target} was cancelled."), target_fallback=_("an item")
)
_system("marketplace.order_disputed", "commerce", _("A buyer opened a dispute on {target}."), target_fallback=YOUR_ITEM)
_system(
    "marketplace.dispute_resolved",
    "commerce",
    _("The dispute on {target} was resolved."),
    target_fallback=_("an order"),
)
_system("marketplace.review_received", "commerce", _("You received a new review."))
_system("payments.refunded", "commerce", _("A refund was issued to you."))
_system("payments.unfulfilled", "commerce", _("Your payment couldn't be applied, so it's being refunded."))
_system("payments.payout_paid", "commerce", _("Your payout was sent."))
_system("payments.payout_rejected", "commerce", _("Your payout request was declined."))

# ---------------------------------------------------------- podcasts, media
_system("podcast.new_episode", "podcasts", _("New episode of {target}."), target_fallback=_("a podcast you follow"))
_system(
    "podcast.guest_added",
    "podcasts",
    _("You were added as a guest on {target}. Confirm to appear on your profile."),
    target_fallback=_("a podcast"),
)
_system("media.failed", "media", _("Your upload couldn't be processed."), text_data=("error",))

# ---------------------------------------------------------------- security
_system(
    "security.suspicious_login",
    "security",
    _("New sign-in from an unrecognised device or location. If this wasn't you, secure your account."),
)
_system(
    "security.token_reuse",
    "security",
    _("A session was signed out because its credentials were reused. Change your password if this wasn't you."),
)
_system("security.password_changed", "security", _("Your password was changed."))
_system("security.email_changed", "security", _("Your email address was changed."))
_system("security.mfa_enabled", "security", _("Two-step verification was turned on."))
_system("security.mfa_disabled", "security", _("Two-step verification was turned off."))
_system("security.api_key_created", "security", _("A new API key was created for your account."))
