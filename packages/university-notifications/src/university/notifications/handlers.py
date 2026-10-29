"""Turn platform events into notifications.

Each handler reads ids from an event payload and calls :func:`notify`. The
publishing modules never import this module; events for modules that aren't
installed simply never arrive.

By design there are **no notifications for anonymous authors**: routing a
reply to an anonymous author would require linking them to their post.
Recipients of anonymous inbox messages are notified (it's their inbox), with
no actor and nothing about the sender.
Moderation events about anonymous content carry no user id and are skipped.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from university.core.events import Event
from university.notifications import services
from university.notifications.models import Notification
from university.notifications.verbs import has_verb

logger = logging.getLogger("university.notifications")


def _author_of(content_type: str, object_id: Any) -> str | None:
    from university.core.registry import registry

    adapter = registry.content_adapters.get(content_type)
    if adapter is None or not object_id:
        return None
    ref = adapter.resolve(object_id)
    return ref.author_id if ref and not ref.is_anonymous else None


def _mentioned(recipient_id: Any, comment_id: Any) -> bool:
    """A mention notification already covers this comment for this person."""
    return Notification.objects.filter(
        recipient_id=recipient_id, verb="social.mention", target_type="social.comment", target_id=str(comment_id)
    ).exists()


# ------------------------------------------------------------------ social
def on_mention(event: Event) -> None:
    p = event.payload
    comment_id, post_id = p.get("comment_id"), p.get("post_id")
    target = ("social.comment", comment_id) if comment_id else ("social.post", post_id)
    services.notify(
        recipient=p.get("mentioned_user_id"),
        verb="social.mention",
        actor=p.get("author_id"),
        target_type=target[0],
        target_id=target[1],
        data={"post_id": post_id, "comment_id": comment_id},
        group_key=f"social.mention:{target[1]}",
    )


def on_comment(event: Event) -> None:
    p = event.payload
    author, comment_id, post_id = str(p.get("author_id")), p.get("comment_id"), p.get("post_id")
    data = {"post_id": post_id, "comment_id": comment_id}
    covered = {author}
    parent_id = p.get("parent_id")
    if parent_id:
        parent_author = _author_of("social.comment", parent_id)
        if parent_author and parent_author not in covered:
            covered.add(parent_author)
            if not _mentioned(parent_author, comment_id):
                services.notify(
                    recipient=parent_author,
                    verb="social.reply",
                    actor=author,
                    target_type="social.comment",
                    target_id=comment_id,
                    data=data,
                    group_key=f"social.reply:{parent_id}",
                )
    post_author = str(p.get("post_author_id") or "")
    if post_author and post_author not in covered and not _mentioned(post_author, comment_id):
        services.notify(
            recipient=post_author,
            verb="social.comment",
            actor=author,
            target_type="social.post",
            target_id=post_id,
            data=data,
            group_key=f"social.comment:{post_id}",
        )


def on_post_reacted(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("post_author_id"),
        verb="social.reaction",
        actor=p.get("user_id"),
        target_type="social.post",
        target_id=p.get("post_id"),
        data={"kind": p.get("kind")},
        group_key=f"social.reaction:{p.get('post_id')}",
    )


def on_comment_reacted(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("comment_author_id"),
        verb="social.comment_reaction",
        actor=p.get("user_id"),
        target_type="social.comment",
        target_id=p.get("comment_id"),
        data={"kind": p.get("kind")},
        group_key=f"social.comment_reaction:{p.get('comment_id')}",
    )


def on_reposted(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("original_author_id"),
        verb="social.repost",
        actor=p.get("author_id"),
        target_type="social.post",
        target_id=p.get("original_post_id"),
        group_key=f"social.repost:{p.get('original_post_id')}",
    )


def on_follow(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("followee_id"),
        verb="social.follow",
        actor=p.get("follower_id"),
        target_type="users.user",
        target_id=p.get("follower_id"),
        group_key="social.follow",
    )


def on_follow_requested(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("followee_id"),
        verb="social.follow_request",
        actor=p.get("follower_id"),
        target_type="users.user",
        target_id=p.get("follower_id"),
        data={"follow_id": p.get("follow_id")},
        group_key="social.follow_request",
    )


def on_follow_approved(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("follower_id"),
        verb="social.follow_approved",
        actor=p.get("followee_id"),
        target_type="users.user",
        target_id=p.get("followee_id"),
    )


def on_block(event: Event) -> None:
    p = event.payload
    services.remove_between(p.get("blocker_id"), p.get("blocked_id"))


# -------------------------------------------------------------- moderation
def on_action_taken(event: Event) -> None:
    p = event.payload
    target_user = p.get("target_user_id")  # Absent for anonymous content.
    verb = f"moderation.{p.get('action')}"
    if not target_user or not has_verb(verb):
        return
    services.notify(
        recipient=target_user,
        verb=verb,
        target_type=p.get("content_type") or "",
        target_id=p.get("object_id") or "",
        data={"action": p.get("action"), "action_id": p.get("action_id")},
    )


def on_action_reversed(event: Event) -> None:
    p = event.payload
    if p.get("target_user_id"):
        services.notify(
            recipient=p["target_user_id"],
            verb="moderation.reversed",
            target_type=p.get("content_type") or "",
            target_id=p.get("object_id") or "",
            data={"action": p.get("action"), "action_id": p.get("action_id")},
        )


def on_appeal_decided(event: Event) -> None:
    p = event.payload
    outcome = p.get("outcome")
    if p.get("appellant_id") and outcome in ("upheld", "overturned"):
        services.notify(
            recipient=p["appellant_id"],
            verb=f"moderation.appeal_{outcome}",
            data={"appeal_id": p.get("appeal_id"), "outcome": outcome},
        )


# ------------------------------------------------------------- institution
def _membership(verb: str) -> Callable[[Event], None]:
    def handler(event: Event) -> None:
        p = event.payload
        services.notify(
            recipient=p.get("user_id"),
            verb=verb,
            target_type="institution.institution",
            target_id=p.get("institution_id"),
            data={"membership_id": p.get("membership_id"), "role": p.get("role")},
        )

    return handler


# --------------------------------------------------------------- community
def _community(event: Event, verb: str, actor: Any = None, *, dedupe: bool = False, **data: Any) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("user_id"),
        verb=verb,
        actor=actor,
        target_type="community.community",
        target_id=p.get("community_id"),
        data=data,
        group_key=f"{verb}:{p.get('community_id')}" if dedupe else "",
    )


def on_community_invited(event: Event) -> None:
    _community(event, "community.invited", actor=event.payload.get("invited_by"), dedupe=True)


def on_community_joined(event: Event) -> None:
    p = event.payload
    # Joining by yourself (open community, invite link, accepting an invitation)
    # needs no notice; a manager approving your request does.
    if event.actor_id and str(event.actor_id) != str(p.get("user_id")):
        _community(event, "community.approved", dedupe=True)


def on_community_role_changed(event: Event) -> None:
    _community(event, "community.role_changed", role=event.payload.get("role"))


def on_community_removed(event: Event) -> None:
    _community(event, "community.removed")


def on_community_banned(event: Event) -> None:
    _community(event, "community.banned")


def on_community_ownership(event: Event) -> None:
    _community(event, "community.ownership", actor=event.actor_id)


# ------------------------------------------------------------------ events
def _registration(event: Event, verb: str) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("user_id"),
        verb=verb,
        target_type="events.event",
        target_id=p.get("event_id"),
        data={"registration_id": p.get("registration_id"), "status": p.get("status")},
        # A promotion and its confirmation describe the same change: notify once.
        group_key=f"events.registration:{p.get('registration_id')}:{p.get('status')}",
    )


def on_registration_confirmed(event: Event) -> None:
    _registration(event, "events.registered")


def on_registration_promoted(event: Event) -> None:
    held = event.payload.get("status") == "pending_payment"
    _registration(event, "events.promoted_payment" if held else "events.promoted")


NOTICE_VERBS = {"cancelled": "events.cancelled", "rescheduled": "events.rescheduled", "reminder": "events.reminder"}


def on_attendee_notice(event: Event) -> None:
    p = event.payload
    verb = NOTICE_VERBS.get(p.get("kind"))
    if verb:
        services.notify(
            recipient=p.get("user_id"),
            verb=verb,
            target_type="events.event",
            target_id=p.get("event_id"),
            data={"registration_id": p.get("registration_id"), "kind": p.get("kind")},
        )


# ----------------------------------------------------------------- creator
def _creator_verification(verb: str) -> Callable[[Event], None]:
    def handler(event: Event) -> None:
        services.notify(
            recipient=event.payload.get("user_id"), verb=verb, data={"profile_id": event.payload.get("profile_id")}
        )

    return handler


def _campaign_notice(recipient: Any, verb: str, p: Any, **data: Any) -> None:
    services.notify(
        recipient=recipient,
        verb=verb,
        target_type="creator.campaign",
        target_id=p.get("campaign_id"),
        data={"participation_id": p.get("participation_id"), **data},
    )


def on_participation_changed(event: Event) -> None:
    p = event.payload
    creator, owner, status = p.get("creator_user_id"), p.get("owner_id"), p.get("status")
    by_creator = event.actor_id is not None and str(event.actor_id) == str(creator)
    if status == "invited":
        _campaign_notice(creator, "creator.invited", p)
    elif status == "applied":
        _campaign_notice(owner, "creator.applied", p)
    elif status == "accepted":
        if by_creator:  # The creator accepted the brand's invitation.
            _campaign_notice(owner, "creator.invitation_accepted", p)
        else:
            _campaign_notice(creator, "creator.accepted", p)
    elif status in ("shortlisted", "declined", "completed"):
        if not (status == "declined" and by_creator):
            _campaign_notice(creator, f"creator.{status}", p)
    elif status == "withdrawn":
        _campaign_notice(owner, "creator.withdrawn", p)
    elif status == "cancelled":
        _campaign_notice(owner if by_creator else creator, "creator.cancelled", p)


def on_deliverable_submitted(event: Event) -> None:
    _campaign_notice(event.payload.get("owner_id"), "creator.deliverable_submitted", event.payload)


def on_deliverable_reviewed(event: Event) -> None:
    p = event.payload
    verb = "creator.deliverable_approved" if p.get("approved") else "creator.deliverable_changes"
    _campaign_notice(p.get("creator_user_id"), verb, p)


# ---------------------------------------------------------------- commerce
def _order_notice(recipient: Any, verb: str, p: Any) -> None:
    services.notify(
        recipient=recipient,
        verb=verb,
        target_type="marketplace.listing",
        target_id=p.get("listing_id") or "",
        data={"order_id": p.get("order_id"), "reference": p.get("reference")},
    )


def _to(role: str, verb: str) -> Callable[[Event], None]:
    def handler(event: Event) -> None:
        _order_notice(event.payload.get(f"{role}_id"), verb, event.payload)

    return handler


def on_order_cancelled(event: Event) -> None:
    p = event.payload
    recipient = p.get("seller_id") if p.get("cancelled_by") == "buyer" else p.get("buyer_id")
    _order_notice(recipient, "marketplace.order_cancelled", p)


def on_dispute_resolved(event: Event) -> None:
    for role in ("buyer", "seller"):
        _order_notice(event.payload.get(f"{role}_id"), "marketplace.dispute_resolved", event.payload)


def _payment_notice(key: str, verb: str) -> Callable[[Event], None]:
    def handler(event: Event) -> None:
        p = event.payload
        services.notify(
            recipient=p.get(key), verb=verb, data={"reference": p.get("reference"), "payout_id": p.get("payout_id")}
        )

    return handler


# ---------------------------------------------------------- podcasts, media
def on_podcast_notice(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("user_id"),
        verb="podcast.new_episode",
        target_type="podcast.show",
        target_id=p.get("podcast_id"),
        data={"episode_id": p.get("episode_id")},
        group_key=f"podcast.new_episode:{p.get('podcast_id')}",
    )


def on_guest_added(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("user_id"),
        verb="podcast.guest_added",
        target_type="podcast.show",
        target_id=p.get("podcast_id"),
        data={"guest_id": p.get("guest_id"), "episode_id": p.get("episode_id")},
    )


def _media_notice(verb: str) -> Callable[[Event], None]:
    def handler(event: Event) -> None:
        p = event.payload
        services.notify(
            recipient=p.get("owner_id"), verb=verb, data={"asset_id": p.get("asset_id"), "error": p.get("error")}
        )

    return handler


# ---------------------------------------------------------------- security
def _security(verb: str) -> Callable[[Event], None]:
    def handler(event: Event) -> None:
        p = event.payload
        services.notify(recipient=p.get("user_id"), verb=verb, data={"session_id": p.get("session_id")})

    return handler


def on_account_closed(event: Event) -> None:
    services.disable_devices(event.payload.get("user_id"), reason="account_closed")


def on_anonymous_message(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("recipient_id"),
        verb="anonymous.message_received",
        target_type="anonymous.message",
        target_id=p.get("message_id"),
        group_key=f"anonymous.inbox:{p.get('recipient_id')}",
    )


def on_announcement_notice(event: Event) -> None:
    p = event.payload
    urgent = p.get("priority") == "urgent"
    services.notify(
        recipient=p.get("user_id"),
        verb="institution.announcement_urgent" if urgent else "institution.announcement",
        target_type="institution.announcement",
        target_id=p.get("announcement_id"),
        data={"institution_id": p.get("institution_id"), "priority": p.get("priority")},
    )


def on_application_submitted(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("poster_id"),
        verb="opportunities.application",
        actor=p.get("applicant_id"),
        target_type="opportunities.opportunity",
        target_id=p.get("opportunity_id"),
        data={"application_id": p.get("application_id")},
    )


def on_campaign_reviewed(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("advertiser_id"),
        verb="promotions.approved" if p.get("approved") else "promotions.rejected",
        target_type="promotions.campaign",
        target_id=p.get("campaign_id"),
    )


def on_campaign_completed(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("advertiser_id"),
        verb="promotions.completed",
        target_type="promotions.campaign",
        target_id=p.get("campaign_id"),
    )


SUBSCRIPTION_VERBS = {
    "subscriptions.subscription.activated": "subscriptions.activated",
    "subscriptions.subscription.renewal_due": "subscriptions.renewal_due",
    "subscriptions.subscription.expired": "subscriptions.expired",
}


def on_subscription_event(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("user_id"),
        verb=SUBSCRIPTION_VERBS[event.name],
        target_type="subscriptions.subscription",
        target_id=p.get("subscription_id"),
        data={"plan": p.get("plan")},
    )


APPLICATION_VERBS = {
    "shortlisted": "opportunities.shortlisted",
    "hired": "opportunities.hired",
    "rejected": "opportunities.rejected",
}


def on_application_status(event: Event) -> None:
    p = event.payload
    verb = APPLICATION_VERBS.get(p.get("status"))
    if verb:
        services.notify(
            recipient=p.get("applicant_id"),
            verb=verb,
            target_type="opportunities.opportunity",
            target_id=p.get("opportunity_id"),
            data={"application_id": p.get("application_id")},
        )


def on_message_sent(event: Event) -> None:
    """One notification per conversation, refreshed by new messages (never containing their text)."""
    p = event.payload
    for recipient in p.get("recipient_ids") or []:
        services.notify(
            recipient=recipient,
            verb="messaging.message",
            actor=p.get("sender_id"),
            data={"conversation_id": p.get("conversation_id")},
            group_key=f"messaging.conversation:{p.get('conversation_id')}",
        )


def on_message_request(event: Event) -> None:
    p = event.payload
    services.notify(
        recipient=p.get("recipient_id"),
        verb="messaging.request",
        actor=p.get("sender_id"),
        data={"conversation_id": p.get("conversation_id")},
        group_key=f"messaging.request:{p.get('conversation_id')}",
    )


HANDLERS: dict[str, Callable[[Event], None]] = {
    "social.mention.created": on_mention,
    "social.comment.created": on_comment,
    "social.post.reacted": on_post_reacted,
    "social.comment.reacted": on_comment_reacted,
    "social.post.reposted": on_reposted,
    "social.follow.created": on_follow,
    "social.follow.requested": on_follow_requested,
    "social.follow.approved": on_follow_approved,
    "social.block.created": on_block,
    "moderation.action.taken": on_action_taken,
    "moderation.action.reversed": on_action_reversed,
    "moderation.appeal.decided": on_appeal_decided,
    "institution.membership.verified": _membership("institution.membership_verified"),
    "institution.membership.rejected": _membership("institution.membership_rejected"),
    "institution.membership.suspended": _membership("institution.membership_suspended"),
    "institution.membership.revoked": _membership("institution.membership_revoked"),
    "community.member.invited": on_community_invited,
    "community.member.joined": on_community_joined,
    "community.role.changed": on_community_role_changed,
    "community.member.removed": on_community_removed,
    "community.member.banned": on_community_banned,
    "community.ownership.transferred": on_community_ownership,
    "events.registration.promoted": on_registration_promoted,
    "events.registration.confirmed": on_registration_confirmed,
    "events.registration.waitlisted": lambda e: _registration(e, "events.waitlisted"),
    "events.registration.declined": lambda e: _registration(e, "events.declined"),
    "events.registration.expired": lambda e: _registration(e, "events.hold_expired"),
    "events.attendee.notice": on_attendee_notice,
    "creator.verification.approved": _creator_verification("creator.verified"),
    "creator.verification.rejected": _creator_verification("creator.verification_declined"),
    "creator.verification.revoked": _creator_verification("creator.verification_revoked"),
    "creator.participation.changed": on_participation_changed,
    "creator.deliverable.submitted": on_deliverable_submitted,
    "creator.deliverable.reviewed": on_deliverable_reviewed,
    "marketplace.order.created": _to("seller", "marketplace.order_placed"),
    "marketplace.order.paid": _to("seller", "marketplace.order_paid"),
    "marketplace.order.fulfilled": _to("buyer", "marketplace.order_fulfilled"),
    "marketplace.order.completed": _to("seller", "marketplace.order_completed"),
    "marketplace.order.cancelled": on_order_cancelled,
    "marketplace.order.disputed": _to("seller", "marketplace.order_disputed"),
    "marketplace.dispute.resolved": on_dispute_resolved,
    "marketplace.review.created": lambda e: services.notify(
        recipient=e.payload.get("seller_id"),
        verb="marketplace.review_received",
        data={"review_id": e.payload.get("review_id")},
    ),
    "payments.refund.succeeded": _payment_notice("payer_id", "payments.refunded"),
    "payments.payment.unfulfilled": _payment_notice("payer_id", "payments.unfulfilled"),
    "payments.payout.paid": _payment_notice("payee_id", "payments.payout_paid"),
    "payments.payout.rejected": _payment_notice("payee_id", "payments.payout_rejected"),
    "podcast.subscriber.notice": on_podcast_notice,
    "podcast.guest.added": on_guest_added,
    "media.asset.failed": _media_notice("media.failed"),
    "security.login.suspicious": _security("security.suspicious_login"),
    "security.refresh_token.reused": _security("security.token_reuse"),
    "user.password_changed": _security("security.password_changed"),
    "user.email_changed": _security("security.email_changed"),
    "security.mfa.enabled": _security("security.mfa_enabled"),
    "security.mfa.disabled": _security("security.mfa_disabled"),
    "security.api_key.created": _security("security.api_key_created"),
    "user.deleted": on_account_closed,
    "user.banned": on_account_closed,
    "anonymous.message.received": on_anonymous_message,
    "institution.announcement.notice": on_announcement_notice,
    "opportunities.application.submitted": on_application_submitted,
    "opportunities.application.status_changed": on_application_status,
    "messaging.message.sent": on_message_sent,
    "messaging.request.received": on_message_request,
    "promotions.campaign.reviewed": on_campaign_reviewed,
    "promotions.campaign.completed": on_campaign_completed,
    **dict.fromkeys(SUBSCRIPTION_VERBS, on_subscription_event),
}


def handle_event(event: Event) -> None:
    """Single subscriber for every handled event (module level, so it can run async)."""
    handler = HANDLERS.get(event.name)
    if handler is not None:
        handler(event)
