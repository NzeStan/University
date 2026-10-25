"""University Analytics — privacy-conscious event aggregation and dashboards.

An optional *level two* module that depends only on University Core::

    pip install university-analytics

    INSTALLED_APPS = [..., *CORE_APPS, "university.analytics"]

It listens to the platform's ids-only events and keeps **daily counters**
(platform-wide and per scope, e.g. per institution) — never raw events, never
user ids. Unique active users are counted with short-lived keyed hashes in the
cache. Raw-event pipelines (ClickHouse, BigQuery, a warehouse) plug in as
sinks that receive pseudonymised, minimised events.
"""

__version__ = "0.1.0"
