"""Temporal quality metrics for one sign across many published daily horoscopes."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean

from app.domain.natal_chart import ZodiacSign
from app.services.daily_sky import DailyHoroscopeSnapshot

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class DailyTemporalQuality:
    sign: ZodiacSign
    days: int
    exact_repeat_count: int
    high_similarity_pairs: int
    max_similarity: float
    mean_adjacent_similarity: float

    @property
    def has_repetition_problem(self) -> bool:
        return self.exact_repeat_count > 0 or self.max_similarity >= 0.72


def evaluate_same_sign_history(
    snapshots: Sequence[DailyHoroscopeSnapshot],
    sign: ZodiacSign,
) -> DailyTemporalQuality:
    """Measure what one real subscriber sees over time, not diversity between signs today."""

    ordered = sorted(snapshots, key=lambda item: item.forecast_date)
    texts = [next(item.text for item in snapshot.signs if item.sign is sign) for snapshot in ordered]
    normalized = [_normalize(text) for text in texts]
    exact_repeat_count = len(normalized) - len(set(normalized))
    token_sets = [_tokens(text) for text in texts]
    pair_scores = [
        _jaccard(token_sets[left], token_sets[right])
        for left in range(len(token_sets))
        for right in range(left + 1, len(token_sets))
    ]
    adjacent_scores = [
        _jaccard(token_sets[index - 1], token_sets[index])
        for index in range(1, len(token_sets))
    ]
    return DailyTemporalQuality(
        sign=sign,
        days=len(texts),
        exact_repeat_count=exact_repeat_count,
        high_similarity_pairs=sum(score >= 0.72 for score in pair_scores),
        max_similarity=max(pair_scores, default=0.0),
        mean_adjacent_similarity=fmean(adjacent_scores) if adjacent_scores else 0.0,
    )


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in (match.group(0).casefold() for match in _TOKEN_RE.finditer(value))
        if len(token) >= 3
    }


def _jaccard(first: set[str], second: set[str]) -> float:
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split()).strip(" .,!?:;—–-")
