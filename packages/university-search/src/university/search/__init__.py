"""University Search — permission-aware search over every module's content.

An optional *level two* module that depends only on University Core::

    pip install university-search

    INSTALLED_APPS = [..., *CORE_APPS, "university.search"]

It implements Core's search abstraction (:mod:`university.core.providers.search`)
with a database backend (PostgreSQL full-text when available) and an
OpenSearch/Elasticsearch backend, indexes content from ids-only events through
Core's content adapters, and checks every result against the viewer before
returning it.
"""

__version__ = "0.1.0"
