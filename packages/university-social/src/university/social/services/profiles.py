from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db import IntegrityError, transaction

from university.core.exceptions import ValidationError
from university.social.conf import social_settings
from university.social.models import SocialProfile

EDITABLE = ("bio", "website", "requires_follow_approval", "allow_mentions_from", "default_post_visibility")


def get_social_profile(user: Any) -> SocialProfile:
    try:
        with transaction.atomic():
            profile, _ = SocialProfile.objects.get_or_create(user=user)
    except IntegrityError:  # concurrent creation
        profile = SocialProfile.objects.get(user=user)
    return profile


@transaction.atomic
def update_social_profile(user: Any, data: Mapping[str, Any]) -> SocialProfile:
    unknown = set(data) - set(EDITABLE)
    if unknown:
        raise ValidationError(details={field: ["This field cannot be changed."] for field in sorted(unknown)})
    if data.get("default_post_visibility") in social_settings.get("SCOPED_VISIBILITIES", []):
        raise ValidationError(details={"default_post_visibility": ["Audience visibilities must be chosen per post."]})
    profile = get_social_profile(user)
    changed = [field for field, value in data.items() if getattr(profile, field) != value]
    for field in changed:
        setattr(profile, field, data[field])
    if changed:
        profile.save(update_fields=[*changed, "updated_at"])
    return profile
