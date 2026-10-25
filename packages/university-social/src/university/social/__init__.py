"""University Social — posts, comments, reactions, reposts, polls, media and the social graph.

An optional *level two* module that depends only on University Core::

    pip install university-social

    INSTALLED_APPS = [..., *CORE_APPS, "university.social"]

Public API::

    from university.social import services, selectors
    from university.social.feeds import FeedProvider, get_feed
"""

__version__ = "0.1.0"
