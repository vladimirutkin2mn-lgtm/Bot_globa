"""Offline editorial quality heuristics for Numa personal-reading regressions.

This module intentionally does not sit in the production generation path. It turns the
editorial audit into measurable signals without rejecting a good reading at runtime on
one brittle stylistic heuristic.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
_GENERIC_PHRASES = (
    "прислушайтесь к себе",
    "доверьтесь себе",
    "важно помнить",
    "обратите внимание",
    "всё в ваших руках",
    "не бойтесь перемен",
    "найдите баланс",
    "поставьте границы",
    "проявите осознанность",
    "дайте себе время",
    "сосредоточьтесь на себе",
    "позвольте себе",
)


@dataclass(frozen=True, slots=True)
class EditorialQualityReport:
    generic_phrase_hits: tuple[str, ...]
    repeated_section_pairs: tuple[tuple[int, int], ...]
    max_section_similarity: float
    distinct_section_ratio: float
    specificity_score: float

    @property
    def passes_baseline(self) -> bool:
        return (
            len(self.generic_phrase_hits) <= 1
            and self.max_section_similarity < 0.86
            and self.distinct_section_ratio >= 0.75
            and self.specificity_score >= 0.45
        )


def evaluate_editorial_quality(
    sections: Iterable[str],
    *,
    anchors: Iterable[str] = (),
) -> EditorialQualityReport:
    """Measure cliché density, self-repetition and use of case-specific anchor words."""

    values = tuple(_clean(value) for value in sections if _clean(value))
    joined = " ".join(values).casefold().replace("ё", "е")
    generic = tuple(
        phrase for phrase in _GENERIC_PHRASES if phrase.casefold().replace("ё", "е") in joined
    )

    repeated: list[tuple[int, int]] = []
    max_similarity = 0.0
    for left in range(len(values)):
        for right in range(left + 1, len(values)):
            similarity = _similar(values[left], values[right])
            max_similarity = max(max_similarity, similarity)
            if similarity >= 0.82:
                repeated.append((left, right))

    fingerprints = {_fingerprint(value) for value in values}
    distinct_ratio = len(fingerprints) / len(values) if values else 1.0
    anchor_tokens = {
        token
        for anchor in anchors
        for token in _WORD_RE.findall(anchor.casefold().replace("ё", "е"))
        if len(token) >= 4
    }
    output_tokens = set(_WORD_RE.findall(joined))
    specificity = len(anchor_tokens & output_tokens) / len(anchor_tokens) if anchor_tokens else 1.0

    return EditorialQualityReport(
        generic_phrase_hits=generic,
        repeated_section_pairs=tuple(repeated),
        max_section_similarity=max_similarity,
        distinct_section_ratio=distinct_ratio,
        specificity_score=specificity,
    )


def _clean(value: str) -> str:
    return " ".join(value.split()).strip()


def _fingerprint(value: str) -> str:
    return " ".join(_WORD_RE.findall(value.casefold().replace("ё", "е")))


def _similar(first: str, second: str) -> float:
    left = _fingerprint(first)
    right = _fingerprint(second)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()
