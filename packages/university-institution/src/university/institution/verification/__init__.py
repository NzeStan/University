"""Pluggable membership verification.

A verification provider proves that a user really belongs to an institution
in the claimed role. Deployments choose which providers exist
(``INSTITUTION.VERIFICATION_PROVIDERS``) and each institution chooses which
it offers (``Institution.verification_methods``).

Write a provider by subclassing :class:`VerificationProvider`::

    class JAMBRegistryProvider(VerificationProvider):
        key = "jamb"
        label = "JAMB registration number"

        def start(self, *, membership, data, file=None):
            ok = jamb_client.lookup(data["reg_number"], membership.user.display_name)
            return self.create_request(membership, approved=ok, evidence={"source": "jamb"})

and register it::

    UNIVERSITY = {"INSTITUTION": {"VERIFICATION_PROVIDERS": {
        "jamb": "myproject.verification.JAMBRegistryProvider",
    }}}
"""

from __future__ import annotations

from university.institution.verification.base import VerificationProvider, get_provider, list_providers

__all__ = ["VerificationProvider", "get_provider", "list_providers"]
