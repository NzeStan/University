"""Ticket codes: shown to the attendee, scanned at the door, never stored.

A code is an HMAC of the registration id, so it can be displayed again at any
time without storing it. Only a keyed hash of the code is stored, for lookup at
check-in, so a database leak doesn't let anyone mint valid tickets. Both
survive key rotation: every configured key is tried.
"""

from __future__ import annotations

from typing import Any

from university.core.crypto import keyed_hash, keyed_hash_candidates, verify_keyed_hash

CODE_PURPOSE = "events.ticket"
LOOKUP_PURPOSE = "events.ticket_lookup"


def _format(digest: str) -> str:
    raw = digest[:20].upper()
    return "-".join(raw[i : i + 5] for i in range(0, 20, 5))


def normalize(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())[:40]


def new_lookup(registration_id: Any) -> str:
    """The stored lookup hash for a new registration (current key)."""
    code = _format(keyed_hash(str(registration_id), purpose=CODE_PURPOSE))
    return keyed_hash(normalize(code), purpose=LOOKUP_PURPOSE)


def ticket_code(registration: Any) -> str:
    """The attendee's code, derived under whichever key issued it."""
    for digest in keyed_hash_candidates(str(registration.pk), purpose=CODE_PURPOSE):
        code = _format(digest)
        if verify_keyed_hash(normalize(code), registration.ticket_lookup, purpose=LOOKUP_PURPOSE):
            return code
    return _format(keyed_hash(str(registration.pk), purpose=CODE_PURPOSE))


def lookup_candidates(code: str) -> list[str]:
    return keyed_hash_candidates(normalize(code), purpose=LOOKUP_PURPOSE)
