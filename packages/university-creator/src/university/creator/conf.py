"""Settings for the creator module (``UNIVERSITY["CREATOR"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    # Seeded into CreatorCategory on migrate; admins can add, rename or deactivate.
    "CATEGORIES": {
        "music": "Music",
        "comedy": "Comedy",
        "education": "Education",
        "tech": "Technology",
        "fashion": "Fashion",
        "beauty": "Beauty",
        "sports": "Sports",
        "gaming": "Gaming",
        "lifestyle": "Lifestyle",
        "food": "Food",
        "art": "Art and design",
        "photography": "Photography",
        "film": "Film and video",
        "podcasting": "Podcasting",
        "business": "Business",
        "faith": "Faith",
        "health": "Health and fitness",
        "travel": "Travel",
        "news": "News and commentary",
        "other": "Other",
    },
    "MAX_CATEGORIES_PER_PROFILE": 3,
    # External platforms, each reached only through a SocialProvider adapter.
    # "class" defaults to ManualProvider (no API; ownership confirmed by reviewers).
    "PROVIDERS": {
        "tiktok": {"label": "TikTok", "url": "https://www.tiktok.com/@{handle}"},
        "instagram": {"label": "Instagram", "url": "https://www.instagram.com/{handle}"},
        "youtube": {"label": "YouTube", "url": "https://www.youtube.com/@{handle}"},
        "x": {"label": "X", "url": "https://x.com/{handle}"},
        "facebook": {"label": "Facebook", "url": "https://www.facebook.com/{handle}"},
        "spotify": {"label": "Spotify", "url": "https://open.spotify.com/artist/{handle}"},
        "linkedin": {"label": "LinkedIn", "url": "https://www.linkedin.com/in/{handle}"},
        "twitch": {"label": "Twitch", "url": "https://www.twitch.tv/{handle}"},
        "audiomack": {"label": "Audiomack", "url": "https://audiomack.com/{handle}"},
        "boomplay": {"label": "Boomplay", "url": "https://www.boomplay.com/artists/{handle}"},
    },
    "MAX_LINKED_ACCOUNTS": 15,
    # Hours between automatic follower-count refreshes (sync_creator_accounts).
    "SYNC_INTERVAL_HOURS": 24,
    # "verified_users": anyone with a verified email may run campaigns;
    # "permission": only holders of creator.campaigns.manage.
    "CAMPAIGN_POLICY": "verified_users",
    "MAX_OPEN_CAMPAIGNS_PER_USER": 10,
    "CURRENCIES": ["NGN", "GHS", "KES", "ZAR", "XOF", "EGP", "USD"],
    "DEFAULT_CURRENCY": "NGN",
    "MAX_DELIVERABLES": 30,
    # Sponsored content must be disclosed (#ad); creators confirm on submission.
    "DISCLOSURE_REQUIRED_BY_DEFAULT": True,
    # Platform commission on paid sponsorship fees, in basis points (100 = 1%).
    "PLATFORM_FEE_BPS": 0,
    # Analytics: daily aggregates and follower snapshots are kept this long.
    "ANALYTICS_RETENTION_DAYS": 730,
    "ANALYTICS_MAX_RANGE_DAYS": 366,
    # Repeat views by the same viewer within this window count once.
    "VIEW_DEDUPE_HOURS": 24,
    # Public creator page, used in media kits ({handle} substituted).
    "PROFILE_URL": "http://localhost:3000/creators/{handle}",
}

creator_settings = ModuleSettings("CREATOR", DEFAULTS)
