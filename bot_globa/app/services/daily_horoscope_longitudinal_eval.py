"""Longitudinal quality checks for one zodiac sign across many daily snapshots."""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import fmean

from app.domain.natal_chart import ZodiacSign
from app.services.daily_sky import DailyHoroscopeSnapshot

_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[.!?]")


@dataclass(frozen=True, slots=True)
class SignLongitudinalMetrics:
    sign: ZodiacSign
    sample_days: int
    exact_duplicate_ratio: float
    repeated_opening_ratio: float
    repeated_action_ratio: float
    mean_adjacent_similarity: float
    max_adjacent_similarity: float

    @property
    def passes(self) -> bool:
        return (
            self.exact_duplicate_ratio == 0
            and self.repeated_opening_ratio <= 0.10
            and self.repeated_action_ratio <= 0.15
            and self.max_adjacent_similarity < 0.72
        )


def evaluate_longitudinal_daily(
    snapshots: tuple[DailyHoroscopeSnapshot, ...],
) -> tuple[SignLongitudinalMetrics, ...]:
    """Answer the product question: what did each sign receive across recent days?"""

    ordered = tuple(sorted(snapshots, key=lambda item: item.forecast_date))
    return tuple(_evaluate_sign(ordered, sign) for sign in ZodiacSign)


def _evaluate_sign(
    snapshots: tuple[DailyHoroscopeSnapshot, ...],
    sign: ZodiacSign,
) -> SignLongitudinalMetrics:
    texts = [
        next(item.text for item in snapshot.signs if item.sign == sign) for snapshot in snapshots
    ]
    if not texts:
        return SignLongitudinalMetrics(sign, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
    normalized = [_normalize(text) for text in texts]
    exact_duplicates = len(normalized) - len(set(normalized))
    openings = [_normalize(_opening(text)) for text in texts]
    actions = [_normalize(_action(text)) for text in texts]
    adjacent = [
        _jaccard(normalized[index - 1], normalized[index]) for index in range(1, len(texts))
    ]
    denominator = max(len(texts) - 1, 1)
    return SignLongitudinalMetrics(
        sign=sign,
        sample_days=len(texts),
        exact_duplicate_ratio=exact_duplicates / max(len(texts), 1),
        repeated_opening_ratio=_repeat_count(openings) / denominator,
        repeated_action_ratio=_repeat_count(actions) / denominator,
        mean_adjacent_similarity=fmean(adjacent) if adjacent else 0.0,
        max_adjacent_similarity=max(adjacent, default=0.0),
    )


def _repeat_count(values: list[str]) -> int:
    return sum(left == right for left, right in zip(values, values[1:], strict=False))


def _normalize(text: str) -> str:
    return " ".join(_TOKEN_RE.findall(text.casefold()))


def _opening(text: str) -> str:
    return _SENTENCE_RE.split(text, maxsplit=1)[0]


def _action(text: str) -> str:
    parts = [part.strip() for part in _SENTENCE_RE.split(text) if part.strip()]
    return parts[-1] if parts else text


def _jaccard(left: str, right: str) -> float:
    a = {token for token in left.split() if len(token) >= 4}
    b = {token for token in right.split() if len(token) >= 4}
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
