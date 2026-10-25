"""Settings for the community module (``UNIVERSITY["COMMUNITY"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    "KINDS": ["interest", "institution", "campus", "department", "club", "creator", "study_group", "other"],
    # "verified_users": any user with a verified email may create communities;
    # "permission": only holders of community.create.
    "CREATION_POLICY": "verified_users",
    "MAX_OWNED_COMMUNITIES": 10,
    "MAX_MEMBERSHIPS_PER_USER": 500,
    "INVITE_LINK_MAX_DAYS": 30,
    "EXPIRED_INVITE_LINK_RETENTION_DAYS": 30,
    # Permissions each role holds *at its community's scope*. Codes for modules
    # that are not installed are simply unused.
    "ROLE_PERMISSIONS": {
        "owner": [
            "community.manage",
            "community.members.manage",
            "events.manage",
            "podcast.manage",
            "moderation.cases.view",
            "moderation.cases.act",
            "moderation.appeals.decide",
            "social.content.moderate",
        ],
        "admin": [
            "community.members.manage",
            "events.manage",
            "podcast.manage",
            "moderation.cases.view",
            "moderation.cases.act",
            "moderation.appeals.decide",
            "social.content.moderate",
        ],
        "moderator": ["moderation.cases.view", "moderation.cases.act", "social.content.moderate"],
        "member": [],
    },
}

community_settings = ModuleSettings("COMMUNITY", DEFAULTS)
