from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from university.core.events import publish
from university.core.exceptions import Conflict, ValidationError
from university.social import events
from university.social.conf import social_settings
from university.social.constants import ContentStatus
from university.social.models import Poll, PollOption, PollVote, Post
from university.social.selectors import get_visible_post
from university.social.services.common import increment


def create_poll(post: Post, spec: Mapping[str, Any]) -> Poll:
    options = [str(o).strip() for o in spec.get("options") or [] if str(o).strip()]
    low, high = int(social_settings.get("POLL_MIN_OPTIONS", 2)), int(social_settings.get("POLL_MAX_OPTIONS", 4))
    if not low <= len(options) <= high or len({o.lower() for o in options}) != len(options):
        raise ValidationError(details={"poll": [f"Provide {low} to {high} distinct options."]})
    if any(len(o) > 100 for o in options):
        raise ValidationError(details={"poll": ["Options must be at most 100 characters."]})
    hours = spec.get("duration_hours")
    closes_at = None
    if hours is not None:
        max_hours = int(social_settings.get("POLL_MAX_DURATION_DAYS", 14)) * 24
        if not 1 <= int(hours) <= max_hours:
            raise ValidationError(details={"poll": [f"Duration must be between 1 and {max_hours} hours."]})
        closes_at = timezone.now() + dt.timedelta(hours=int(hours))
    poll = Poll.objects.create(post=post, allows_multiple=bool(spec.get("allows_multiple")), closes_at=closes_at)
    PollOption.objects.bulk_create(
        [PollOption(poll=poll, text=text, position=index) for index, text in enumerate(options)]
    )
    return poll


@transaction.atomic
def vote_in_poll(*, user: Any, post_id: Any, option_ids: list[Any]) -> Poll:
    post = get_visible_post(user, post_id)
    poll = Poll.objects.select_for_update().filter(post=post).first()
    if poll is None or post.status != ContentStatus.PUBLISHED:
        raise ValidationError("This post has no open poll.", code="no_poll")
    if poll.closes_at and poll.closes_at <= timezone.now():
        raise ValidationError("This poll is closed.", code="poll_closed")
    unique_ids = list(dict.fromkeys(str(o) for o in option_ids))
    if not unique_ids or (not poll.allows_multiple and len(unique_ids) != 1):
        raise ValidationError(
            details={"options": ["Choose one option." if not poll.allows_multiple else "Choose options."]}
        )
    options = list(PollOption.objects.filter(poll=poll, pk__in=unique_ids))
    if len(options) != len(unique_ids):
        raise ValidationError(details={"options": ["Unknown option."]})
    first_vote = not PollVote.objects.filter(poll=poll, user=user).exists()
    try:
        with transaction.atomic():
            PollVote.objects.bulk_create(
                [PollVote(poll=poll, option=o, user=user, single_choice=not poll.allows_multiple) for o in options]
            )
    except IntegrityError:
        raise Conflict("You have already voted.", code="already_voted") from None
    for option in options:
        increment(PollOption, option.pk, "vote_count", +1)
    if first_vote:
        increment(Poll, poll.pk, "total_votes", +1)
    publish(events.POLL_VOTED, {"post_id": post.pk, "poll_id": poll.pk}, actor=user)
    poll.refresh_from_db()
    return poll
