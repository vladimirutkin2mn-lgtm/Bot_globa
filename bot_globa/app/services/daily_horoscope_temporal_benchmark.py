"""Temporal quality metrics for one zodiac sign across many daily snapshots."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations

_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class TemporalDailyItem:
    date: str
    text: str
    headline: str = ""
    central_idea: str = ""
    action: str = ""


@dataclass(frozen=True, slots=True)
class TemporalDailyReport:
    sample_size: int
    exact_duplicate_pairs: int
    near_duplicate_pairs: int
    repeated_headline_pairs: int
    repeated_idea_pairs: int
    repeated_action_pairs: int
    max_text_similarity: float

    @property
    def passes_baseline(self) -> bool:
        return (
            self.exact_duplicate_pairs == 0
            and self.near_duplicate_pairs == 0
            and self.repeated_headline_pairs == 0
            and self.repeated_idea_pairs == 0
            and self.repeated_action_pairs <= 1
        )


def evaluate_temporal_daily(items: list[TemporalDailyItem]) -> TemporalDailyReport:
    """Answer the product question: what did this same sign receive over the last N days?"""

    exact = near = headlines = ideas = actions = 0
    max_similarity = 0.0
    for first, second in combinations(items, 2):
        text_similarity = _similar(first.text, second.text)
        max_similarity = max(max_similarity, text_similarity)
        if _normal(first.text) == _normal(second.text):
            exact += 1
        elif text_similarity >= 0.88:
            near += 1
        if first.headline and second.headline and _similar(first.headline, second.headline) >= 0.86:
            headlines += 1
        if (
            first.central_idea
            and second.central_idea
            and _idea(first.central_idea, second.central_idea) >= 0.78
        ):
            ideas += 1
        if first.action and second.action and _idea(first.action, second.action) >= 0.78:
            actions += 1
    return TemporalDailyReport(
        sample_size=len(items),
        exact_duplicate_pairs=exact,
        near_duplicate_pairs=near,
        repeated_headline_pairs=headlines,
        repeated_idea_pairs=ideas,
        repeated_action_pairs=actions,
        max_text_similarity=max_similarity,
    )


def _normal(value: str) -> str:
    return " ".join(_WORD_RE.findall(value.casefold().replace("ё", "е")))


def _similar(first: str, second: str) -> float:
    left = _normal(first)
    right = _normal(second)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _idea(first: str, second: str) -> float:
    left = set(_normal(first).split())
    right = set(_normal(second).split())
    if not left or not right:
        return 0.0
    return max(_similar(first, second), len(left & right) / len(left | right))
