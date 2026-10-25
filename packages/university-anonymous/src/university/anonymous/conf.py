"""Settings for the anonymous module (``UNIVERSITY["ANONYMOUS"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    # Audiences anonymous posts may target. Add "public" to allow platform-wide
    # anonymous posts (not recommended: audience-scoped boards are safer).
    "ALLOWED_VISIBILITIES": ["institution", "campus", "community"],
    "POST_MAX_LENGTH": 3000,
    "COMMENT_MAX_LENGTH": 1000,
    # Abuse gates for posting.
    "MIN_ACCOUNT_AGE_HOURS": 24,
    "REQUIRE_VERIFIED_EMAIL": True,
    # Stored and displayed creation times are rounded down to this many
    # seconds, defeating timing correlation with other activity.
    "TIMESTAMP_PRECISION_SECONDS": 300,
    # Fernet keys (urlsafe base64, 32 bytes) for the encrypted identity store.
    # The first key encrypts; all keys decrypt (rotation). Empty -> a key is
    # derived from SECURITY.HMAC_KEY / SECRET_KEY (a system check warns).
    "IDENTITY_KEYS": [],
    # Two-person rule for identity reveals.
    "REVEAL_REQUIRES_APPROVAL": True,
    "REVEAL_APPROVAL_TTL_HOURS": 24,
    "REVEAL_MIN_JUSTIFICATION": 30,
    # Label the post author's comments as "OP" within their own thread.
    "SHOW_OP_LABEL": True,
    "REACTION_TYPES": ["like", "support", "laugh", "sad"],
    "PSEUDONYM_ADJECTIVES": [
        "Quiet",
        "Brave",
        "Curious",
        "Gentle",
        "Swift",
        "Bright",
        "Calm",
        "Clever",
        "Bold",
        "Kind",
        "Witty",
        "Silent",
        "Sunny",
        "Steady",
        "Wise",
        "Lively",
        "Patient",
        "Cheerful",
        "Humble",
        "Noble",
    ],
    "PSEUDONYM_NOUNS": [
        "Lion",
        "Elephant",
        "Zebra",
        "Giraffe",
        "Cheetah",
        "Leopard",
        "Rhino",
        "Hippo",
        "Gazelle",
        "Buffalo",
        "Eagle",
        "Heron",
        "Crane",
        "Falcon",
        "Pelican",
        "Baobab",
        "Kudu",
        "Impala",
        "Okapi",
        "Meerkat",
        "Hornbill",
        "Weaver",
        "Sunbird",
        "Tortoise",
        "Pangolin",
        "Antelope",
        "Flamingo",
        "Ostrich",
        "Oryx",
        "Iroko",
    ],
}

anonymous_settings = ModuleSettings("ANONYMOUS", DEFAULTS)
