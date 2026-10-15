"""Editorial quality metrics layered on top of the structured/safety validators.

Production validators answer "is this grounded and safe?". This evaluator answers the second
question from the audit: "is this specific, non-repetitive and worth sending?". It is offline
research only and therefore adds no user-facing latency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations
from statistics import fmean

from app.domain.horoscope import AstrologyReadingResult
from app.domain.reading_result import ReadingResult
from app.research.oracle_llm_dataset import OracleResearchCase

_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
_GENERIC_PHRASES = (
    "прислушайтесь к себе",
    "доверьтесь интуиции",
    "всё в ваших руках",
    "важно помнить",
    "не забывайте",
    "сохраняйте баланс",
    "установите границы",
    "обозначьте границы",
    "сфокусируйтесь на своих потребностях",
    "дайте себе время",
    "будьте честны с собой",
)


@dataclass(frozen=True, slots=True)
class EditorialQualityMetrics:
    specificity: float
    section_novelty: float
    scenario_distinctness: float
    practical_step_specificity: float
    genericity: float
    central_thesis_signal: float

    @property
    def score(self) -> float:
        return 100.0 * (
            0.24 * self.specificity
            + 0.22 * self.section_novelty
            + 0.18 * self.scenario_distinctness
            + 0.18 * self.practical_step_specificity
            + 0.12 * self.central_thesis_signal
            + 0.06 * (1.0 - self.genericity)
        )

    @property
    def passes(self) -> bool:
        return (
            self.specificity >= 0.5
            and self.section_novelty >= 0.55
            and self.scenario_distinctness >= 0.45
            and self.practical_step_specificity >= 0.45
            and self.genericity <= 0.34
        )


def evaluate_editorial_quality(
    case: OracleResearchCase,
    result: ReadingResult | AstrologyReadingResult,
) -> EditorialQualityMetrics:
    sections = _sections(result)
    body = " ".join(sections).casefold()
    specificity = _presence_ratio(body, case.specificity_terms, target=2)
    section_novelty = _novelty(sections)
    scenarios = [scenario.scenario for scenario in result.possible_scenarios]
    scenario_distinctness = _novelty(scenarios)
    practical = result.practical_step.casefold()
    source_terms = _tokens(" ".join((case.question, case.context or "", *sections)))
    practical_terms = _tokens(practical)
    overlap = _jaccard(practical_terms, source_terms)
    action_marker = (
        1.0
        if re.search(
            r"\b(сделайте|проверьте|спросите|скажите|сравните|выберите|запишите|наблюдайте|"
            r"уточните|попробуйте|отделите|зафиксируйте|обсудите|решите)\b",
            practical,
        )
        else 0.0
    )
    practical_specificity = min(1.0, 0.55 * action_marker + 0.9 * overlap)
    generic_hits = sum(phrase in body for phrase in _GENERIC_PHRASES)
    genericity = min(generic_hits / 3.0, 1.0)
    opening = result.overview if isinstance(result, AstrologyReadingResult) else result.opening
    opening_terms = _tokens(opening)
    question_terms = _tokens(case.question)
    central_thesis_signal = min(1.0, 0.35 + 1.6 * _jaccard(opening_terms, question_terms))
    return EditorialQualityMetrics(
        specificity=specificity,
        section_novelty=section_novelty,
        scenario_distinctness=scenario_distinctness,
        practical_step_specificity=practical_specificity,
        genericity=genericity,
        central_thesis_signal=central_thesis_signal,
    )


def repeated_phrase_flags(
    results: tuple[ReadingResult | AstrologyReadingResult, ...],
) -> dict[str, int]:
    """Detect cross-answer editorial habits such as the same advice appearing repeatedly."""

    counts: dict[str, int] = {}
    for result in results:
        body = " ".join(_sections(result)).casefold()
        for phrase in _GENERIC_PHRASES:
            if phrase in body:
                counts[phrase] = counts.get(phrase, 0) + 1
    return {phrase: count for phrase, count in counts.items() if count > 1}


def _sections(result: ReadingResult | AstrologyReadingResult) -> list[str]:
    if isinstance(result, AstrologyReadingResult):
        return [
            result.overview,
            *(item.text for item in result.interpretations),
            *result.themes,
            *(item.scenario for item in result.possible_scenarios),
            result.practical_step,
        ]
    return [
        result.opening,
        *(item.interpretation for item in result.symbols),
        *result.patterns,
        *(item.scenario for item in result.possible_scenarios),
        result.practical_step,
    ]


def _novelty(values: list[str]) -> float:
    cleaned = [_tokens(value) for value in values if value.strip()]
    if len(cleaned) < 2:
        return 1.0
    overlaps = [_jaccard(left, right) for left, right in combinations(cleaned, 2)]
    return 1.0 - fmean(overlaps)


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(value) if len(token) >= 4}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _presence_ratio(text: str, terms: tuple[str, ...], *, target: int) -> float:
    if not terms:
        return 1.0
    found = sum(term.casefold() in text for term in terms)
    return min(found / target, 1.0)
