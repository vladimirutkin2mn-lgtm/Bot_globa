"""Deterministic offline editorial-quality signals for generated Numa readings."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.reading_result import ReadingResult

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOCK_PHRASES = (
    "сейчас важно",
    "главное сейчас",
    "вам стоит",
    "доверьтесь себе",
    "прислушайтесь к себе",
    "установить границы",
    "поставить границы",
    "вести дневник",
)


@dataclass(frozen=True, slots=True)
class OracleTextQuality:
    max_section_similarity: float
    stock_phrase_hits: int
    repeated_openings: int

    @property
    def needs_editorial_review(self) -> bool:
        return (
            self.max_section_similarity >= 0.68
            or self.stock_phrase_hits >= 2
            or self.repeated_openings >= 2
        )


def evaluate_reading_editorial_quality(result: ReadingResult) -> OracleTextQuality:
    """Flag generic/redundant copy without making runtime generation brittle."""

    sections = [
        result.title,
        result.opening,
        *result.patterns,
        result.practical_step,
        result.share_card.headline,
        result.share_card.short_text,
    ]
    token_sets = [_tokens(value) for value in sections]
    similarities = [
        _jaccard(token_sets[left], token_sets[right])
        for left in range(len(token_sets))
        for right in range(left + 1, len(token_sets))
    ]
    lowered = "\n".join(sections).casefold()
    stock_hits = sum(lowered.count(phrase) for phrase in _STOCK_PHRASES)
    openings = [_opening(value) for value in sections if value.strip()]
    repeated_openings = len(openings) - len(set(openings))
    return OracleTextQuality(
        max_section_similarity=max(similarities, default=0.0),
        stock_phrase_hits=stock_hits,
        repeated_openings=repeated_openings,
    )


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in (match.group(0).casefold() for match in _TOKEN_RE.finditer(value))
        if len(token) >= 3
    }


def _opening(value: str) -> tuple[str, ...]:
    return tuple(list(_tokens_in_order(value))[:3])


def _tokens_in_order(value: str) -> list[str]:
    return [
        token
        for token in (match.group(0).casefold() for match in _TOKEN_RE.finditer(value))
        if len(token) >= 3
    ]


def _jaccard(first: set[str], second: set[str]) -> float:
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)
