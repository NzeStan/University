"""University Moderation — reports, cases, actions, appeals and automated rules.

An optional *level two* module that depends only on University Core. It
moderates any content type registered through Core content adapters
(``social.post``, ``anonymous.post``, ``users.user`` …) without importing the
modules that own them::

    pip install university-moderation

    INSTALLED_APPS = [..., *CORE_APPS, "university.moderation"]
"""

__version__ = "0.1.1"
