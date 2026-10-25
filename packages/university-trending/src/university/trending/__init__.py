"""University Trending — a configurable trending engine.

An optional *level two* module that depends only on University Core::

    pip install university-trending

    INSTALLED_APPS = [..., *CORE_APPS, "university.trending"]

It turns ids-only engagement events (views, reactions, comments, shares,
registrations, joins, orders) into hourly signal buckets, then scores content
by weighted engagement, velocity and recency — not by total likes. Feeds use
the scores through Core's ``content.trending_scores`` hook.
"""

__version__ = "0.1.0"
