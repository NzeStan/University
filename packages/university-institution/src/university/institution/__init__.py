"""University Institution — institutions, campuses, academic structure and memberships.

An optional *level two* module. Install with::

    pip install university-institution

and add ``"university.institution"`` to ``INSTALLED_APPS``.

Public API::

    from university.institution import services, selectors
    from university.institution.models import Institution, InstitutionMembership
    from university.institution.verification import VerificationProvider
"""

__version__ = "0.1.0"
