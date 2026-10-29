"""University Community — communities with roles, privacy, invitations and delegated moderation.

An optional *level two* module that depends only on University Core::

    pip install university-community

    INSTALLED_APPS = [..., *CORE_APPS, "university.community"]

Communities are audiences: active members belong to the ``("community", id)``
scope, so community-only social posts, anonymous community boards and
community-scoped moderation work without those modules knowing about
communities.
"""

__version__ = "0.1.2"
