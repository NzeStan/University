"""Anti-spam abstraction.

Content-creating modules ask the configured :class:`SpamFilter` for a verdict
before accepting user content. Core ships a dependency-free rule-based filter;
AI or third-party moderation providers implement the same protocol in their
own packages — Core never requires an external AI service.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class SpamAction(StrEnum):
    ALLOW = "allow"
    REVIEW = "review"  # accept but queue for human moderation
    REJECT = "reject"


@dataclass(frozen=True)
class SpamVerdict:
    action: SpamAction
    score: float = 0.0
    #: Machine-readable reasons, kept for explainable, auditable decisions.
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def allowed(self) -> bool:
        return self.action != SpamAction.REJECT


class SpamFilter(Protocol):
    def check(self, text: str, *, actor: Any = None, context: Mapping[str, Any] | None = None) -> SpamVerdict: ...


class NullSpamFilter:
    def check(self, text: str, *, actor: Any = None, context: Mapping[str, Any] | None = None) -> SpamVerdict:
        return SpamVerdict(SpamAction.ALLOW)


_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_REPEAT_RE = re.compile(r"(.)\1{9,}")


class RuleBasedSpamFilter:
    """Simple, explainable heuristics: links, repetition, shouting, blocklist."""

    def __init__(
        self,
        *,
        max_links: int = 5,
        review_score: float = 0.5,
        reject_score: float = 0.9,
        blocked_terms: Iterable[str] = (),
    ) -> None:
        self.max_links = max_links
        self.review_score = review_score
        self.reject_score = reject_score
        self.blocked_terms = tuple(t.lower() for t in blocked_terms)

    def check(self, text: str, *, actor: Any = None, context: Mapping[str, Any] | None = None) -> SpamVerdict:
        score = 0.0
        reasons: list[str] = []
        lowered = text.lower()
        links = len(_URL_RE.findall(text))
        if links > self.max_links:
            score += 0.6
            reasons.append("too_many_links")
        if _REPEAT_RE.search(text):
            score += 0.3
            reasons.append("repeated_characters")
        letters = [c for c in text if c.isalpha()]
        if len(letters) >= 20 and sum(c.isupper() for c in letters) / len(letters) > 0.8:
            score += 0.2
            reasons.append("excessive_capitals")
        if any(term in lowered for term in self.blocked_terms):
            score += 1.0
            reasons.append("blocked_term")
        score = min(score, 1.0)
        if score >= self.reject_score:
            action = SpamAction.REJECT
        elif score >= self.review_score:
            action = SpamAction.REVIEW
        else:
            action = SpamAction.ALLOW
        return SpamVerdict(action, score, tuple(reasons))
