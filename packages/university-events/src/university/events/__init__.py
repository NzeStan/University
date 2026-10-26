"""University Events — events, venues, schedules, registration, waitlists, tickets and check-in.

An optional *level two* module that depends only on University Core::

    pip install university-events

    INSTALLED_APPS = [..., *CORE_APPS, "university.events"]

Events can be hosted by a person or by any scope (an institution, a
community) and shown to that scope's members only, without this module
importing the module that defines the scope. Ticketing is free by default;
paid tickets plug into a payments module through events, never imports.
"""

__version__ = "0.1.1"
