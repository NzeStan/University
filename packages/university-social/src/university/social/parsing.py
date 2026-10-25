"""Extraction of hashtags, mentions and links from user text.

Pure functions, no I/O. Links are recorded but never fetched here — link
previews (which would make the server issue requests to user-supplied URLs,
an SSRF risk) belong to a dedicated, sandboxed worker.
"""

from __future__ import annotations

import re

# Unicode-aware hashtags (Yoruba, Hausa, Igbo, Swahili … diacritics work).
_HASHTAG_RE = re.compile(r"(?<![\w#])#(\w{1,64})", re.UNICODE)
_MENTION_RE = re.compile(r"(?<![\w@])@([a-zA-Z0-9](?:[a-zA-Z0-9_]{1,28}[a-zA-Z0-9])?)")
_URL_RE = re.compile(r"https?://[^\s<>\"'()]{3,2000}", re.IGNORECASE)


def _unique(items: list[str], limit: int) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
        if len(seen) >= limit:
            break
    return list(seen)


def extract_hashtags(text: str, *, limit: int) -> list[str]:
    tags = [m.group(1).lower() for m in _HASHTAG_RE.finditer(text or "") if not m.group(1).isdigit()]
    return _unique(tags, limit)


def extract_mentions(text: str, *, limit: int) -> list[str]:
    return _unique([m.group(1).lower() for m in _MENTION_RE.finditer(text or "")], limit)


def extract_links(text: str, *, limit: int) -> list[str]:
    return _unique([m.group(0).rstrip(".,!?;:") for m in _URL_RE.finditer(text or "")], limit)
