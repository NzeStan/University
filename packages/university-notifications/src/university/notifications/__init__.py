"""University Notifications — in-app, email, push and SMS notifications.

An optional *level two* module that depends only on University Core::

    pip install university-notifications

    INSTALLED_APPS = [..., *CORE_APPS, "university.notifications"]

Notifications are driven by events: social, moderation, institution,
community and security modules publish events with ids only, and this
module turns them into notifications without any of them importing it.
Project code can notify directly with :func:`university.notifications.services.notify`.
"""

__version__ = "0.1.0"
