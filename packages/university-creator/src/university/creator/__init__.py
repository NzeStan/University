"""University Creator — creator profiles, verification, media kits, campaigns and analytics.

An optional *level two* module that depends only on University Core::

    pip install university-creator

    INSTALLED_APPS = [..., *CORE_APPS, "university.creator"]

External platforms (TikTok, Instagram, YouTube, X, Facebook, Spotify …) are
reached only through :class:`university.creator.providers.SocialProvider`
adapters, configured per deployment. Analytics are daily aggregates built
from ids-only platform events; no viewer-level records are kept.
"""

__version__ = "0.1.2"
