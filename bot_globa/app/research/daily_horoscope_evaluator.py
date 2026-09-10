"""Fixed evaluator for Numa daily-horoscope autoresearch.

The autonomous agent must never edit this module during an experiment run. It provides a
deterministic 60-day evaluation window, hard product gates and one comparable numa_score.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from itertools import combinations, pairwise
from statistics import fmean

from app.bot.daily_horoscope import render_daily_horoscope
from app.bot.scene_media import TELEGRAM_CAPTION_LIMIT
from app.domain.natal_chart import ZodiacSign
from app.research.daily_horoscope_candidate import build_candidate_daily_horoscope
from app.services.daily_horoscope_benchmark import BenchmarkForecast, build_benchmark_metrics
from app.services.daily_horoscope_editorial import build_editorial_daily_horoscope
from app.services.daily_sky import DailyHoroscopeSnapshot

RESEARCH_START_DATE = date(2026, 7, 1)
RESEARCH_DAYS = 60
SEMANTIC_REVIEW_DAYS = 14
SEMANTIC_REPEAT_SIMILARITY = 0.80
MAX_SEMANTIC_NEAR_REPEAT_RATE = 0.18
MAX_SEMANTIC_NEAR_REPEAT_RATE_PER_SIGN = 0.30
MAX_SEMANTIC_FINDINGS = 12
MIN_ACTIONABLE_RATIO = 0.75
MIN_TOPIC_COVERAGE_RATIO = 0.45
MIN_TOPIC_VARIETY = 5
MIN_TEMPORAL_DIVERSITY = 0.70
MIN_DISTINCT_TEXTS_PER_SIGN = 8
MIN_AVG_WORDS = 5.0
MAX_AVG_WORDS = 10.5
MAX_FORECAST_WORDS = 13

_TOKEN_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
_TOKEN_STOPWORDS = frozenset(
    {
        "вам",
        "вас",
        "ваш",
        "для",
        "если",
        "как",
        "или",
        "это",
        "уже",
        "что",
        "сегодня",
        "сначала",
        "потом",
    }
)

# These broad concepts intentionally collapse common Russian paraphrases. The review is not
# pretending to be an embedding model: it is a deterministic product guard that catches the
# repetitive meaning patterns our short editorial templates are most likely to produce.
_SEMANTIC_CONCEPT_ROOTS: dict[str, tuple[str, ...]] = {
    "finance": (
        "деньг",
        "денеж",
        "финанс",
        "бюджет",
        "расход",
        "трат",
        "выгод",
        "цифр",
    ),
    "relationships": (
        "отношен",
        "любов",
        "симпат",
        "взаимн",
        "близк",
        "семь",
    ),
    "work": (
        "работ",
        "карьер",
        "проект",
        "задач",
        "дел",
        "навык",
    ),
    "communication": (
        "разговор",
        "переписк",
        "сообщен",
        "вопрос",
        "ответ",
        "говор",
        "выслуш",
        "проговор",
    ),
    "learning_travel": (
        "обуч",
        "информац",
        "источник",
        "поезд",
        "дорог",
        "знан",
    ),
    "energy_rest": (
        "устал",
        "отдых",
        "энерг",
        "пауза",
        "тишин",
        "ритм",
    ),
    "choice_plan": (
        "выбор",
        "план",
        "цель",
        "решен",
        "решён",
        "вариант",
        "возможност",
    ),
    "inspect": (
        "проверь",
        "перепров",
        "перечит",
        "уточн",
        "оцен",
        "сравн",
        "свер",
        "зафикс",
    ),
    "communicate_action": (
        "задай",
        "задайте",
        "поговор",
        "обсуд",
        "назов",
        "обознач",
        "выслуш",
        "проговор",
        "говорите",
    ),
    "take_action": (
        "сдела",
        "шаг",
        "начн",
        "инициир",
        "исправ",
        "покаж",
        "идите",
        "решите",
    ),
    "slow_down": (
        "не спеш",
        "не тороп",
        "остав",
        "останов",
        "освобод",
        "снимите",
        "не дав",
    ),
    "boundaries": (
        "границ",
        "отдел",
        "не додум",
        "обязательств",
        "услови",
        "роли",
    ),
}

SnapshotBuilder = Callable[[date], DailyHoroscopeSnapshot]


@dataclass(frozen=True, slots=True)
class SemanticRepeatFinding:
    sign: str
    first_date: str
    second_date: str
    similarity: float
    first_text: str
    second_text: str

    def payload(self) -> dict[str, object]:
        return {
            "sign": self.sign,
            "first_date": self.first_date,
            "second_date": self.second_date,
            "similarity": round(self.similarity, 4),
            "first_text": self.first_text,
            "second_text": self.second_text,
        }


@dataclass(frozen=True, slots=True)
class ResearchMetrics:
    avg_words: float
    avg_chars: float
    max_words: int
    max_caption_chars: int
    daily_unique_ratio: float
    lexical_diversity: float
    unique_opening_ratio: float
    topic_coverage_ratio: float
    topic_variety: int
    topic_balance: float
    actionable_ratio: float
    temporal_diversity: float
    distinct_text_ratio: float
    min_distinct_texts_per_sign: int
    adjacent_repeat_rate: float
    semantic_review_days: int
    semantic_review_cells: int
    semantic_review_pairs: int
    semantic_near_repeat_rate: float
    max_semantic_near_repeat_rate_per_sign: float
    max_semantic_similarity: float

    def payload(self) -> dict[str, object]:
        payload = asdict(self)
        return {
            key: round(value, 4) if isinstance(value, float) else value
            for key, value in payload.items()
        }


@dataclass(frozen=True, slots=True)
class ResearchEvaluation:
    numa_score: float
    quality_score: float
    gates_passed: bool
    hard_gates: dict[str, bool]
    metrics: ResearchMetrics
    semantic_repeats: tuple[SemanticRepeatFinding, ...] = ()

    def payload(self) -> dict[str, object]:
        return {
            "numa_score": round(self.numa_score, 4),
            "quality_score": round(self.quality_score, 4),
            "gates_passed": self.gates_passed,
            "hard_gates": dict(sorted(self.hard_gates.items())),
            "metrics": self.metrics.payload(),
            "semantic_repeats": [item.payload() for item in self.semantic_repeats],
        }


@dataclass(frozen=True, slots=True)
class ResearchComparison:
    candidate: ResearchEvaluation
    baseline: ResearchEvaluation

    @property
    def delta(self) -> float:
        return self.candidate.numa_score - self.baseline.numa_score

    def payload(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.payload(),
            "baseline": self.baseline.payload(),
            "delta": round(self.delta, 4),
            "candidate_beats_baseline": self.candidate.gates_passed and self.delta > 0.0,
            "window": {
                "start_date": RESEARCH_START_DATE.isoformat(),
                "days": RESEARCH_DAYS,
                "semantic_review_days": SEMANTIC_REVIEW_DAYS,
                "semantic_review_signs": len(ZodiacSign),
            },
        }


def evaluate_current_candidate() -> ResearchComparison:
    """Compare the editable candidate with the current production editorial baseline."""

    return ResearchComparison(
        candidate=evaluate_builder(build_candidate_daily_horoscope),
        baseline=evaluate_builder(build_editorial_daily_horoscope),
    )


def evaluate_builder(
    builder: SnapshotBuilder,
    *,
    start_date: date = RESEARCH_START_DATE,
    days: int = RESEARCH_DAYS,
) -> ResearchEvaluation:
    """Evaluate one builder on a fixed deterministic date window."""

    if days < 2:
        raise ValueError("autoresearch evaluation needs at least two days")

    daily_metrics = []
    per_sign_texts: dict[ZodiacSign, list[str]] = {sign: [] for sign in ZodiacSign}
    topic_counts: Counter[str] = Counter()
    max_caption_chars = 0
    max_words = 0
    daily_unique_ratios: list[float] = []

    for offset in range(days):
        forecast_date = start_date + timedelta(days=offset)
        snapshot = builder(forecast_date)
        _validate_snapshot_shape(snapshot, forecast_date)

        texts = [item.text.strip() for item in snapshot.signs]
        if any(not text for text in texts):
            raise ValueError("autoresearch candidate returned empty sign copy")

        daily_unique_ratios.append(len(set(texts)) / len(ZodiacSign))
        max_caption_chars = max(max_caption_chars, len(render_daily_horoscope(snapshot)))
        for text in texts:
            max_words = max(max_words, _word_count(text))

        forecasts = [BenchmarkForecast(sign=item.sign, text=item.text) for item in snapshot.signs]
        daily_metric = build_benchmark_metrics(forecasts)
        daily_metrics.append(daily_metric)
        topic_counts.update(daily_metric.topic_distribution)

        for item in snapshot.signs:
            per_sign_texts[item.sign].append(item.text)

    avg_words = fmean(item.avg_words for item in daily_metrics)
    avg_chars = fmean(item.avg_chars for item in daily_metrics)
    lexical_diversity = fmean(item.lexical_diversity for item in daily_metrics)
    unique_opening_ratio = fmean(item.unique_opening_ratio for item in daily_metrics)
    topic_coverage_ratio = fmean(item.topic_coverage_ratio for item in daily_metrics)
    actionable_ratio = fmean(item.actionable_ratio for item in daily_metrics)

    non_other_topics = {topic: count for topic, count in topic_counts.items() if topic != "other"}
    topic_variety = len(non_other_topics)
    topic_balance = _normalized_entropy(tuple(non_other_topics.values()))

    temporal_diversities: list[float] = []
    distinct_ratios: list[float] = []
    distinct_counts: list[int] = []
    repeat_count = 0
    pair_count = 0

    for texts in per_sign_texts.values():
        distinct_count = len(set(texts))
        distinct_counts.append(distinct_count)
        distinct_ratios.append(distinct_count / len(texts))

        for previous, current in pairwise(texts):
            pair_count += 1
            if previous == current:
                repeat_count += 1
            temporal_diversities.append(1.0 - _jaccard(_tokens(previous), _tokens(current)))

    semantic_review_days = min(days, SEMANTIC_REVIEW_DAYS)
    semantic_review_cells = semantic_review_days * len(ZodiacSign)
    semantic_review_pairs = 0
    semantic_repeat_count = 0
    max_semantic_similarity = 0.0
    per_sign_semantic_rates: list[float] = []
    semantic_findings: list[SemanticRepeatFinding] = []

    for sign, texts in per_sign_texts.items():
        reviewed = texts[:semantic_review_days]
        sign_pairs = 0
        sign_repeats = 0
        for first_index, second_index in combinations(range(len(reviewed)), 2):
            first = reviewed[first_index]
            second = reviewed[second_index]
            # Exact duplicates already have their own gate. This review deliberately measures
            # meaning-preserving surface variation that an exact-string check would miss.
            if first == second:
                continue
            sign_pairs += 1
            semantic_review_pairs += 1
            similarity = _semantic_similarity(first, second)
            max_semantic_similarity = max(max_semantic_similarity, similarity)
            if similarity < SEMANTIC_REPEAT_SIMILARITY:
                continue
            sign_repeats += 1
            semantic_repeat_count += 1
            semantic_findings.append(
                SemanticRepeatFinding(
                    sign=sign.value,
                    first_date=(start_date + timedelta(days=first_index)).isoformat(),
                    second_date=(start_date + timedelta(days=second_index)).isoformat(),
                    similarity=similarity,
                    first_text=first,
                    second_text=second,
                )
            )
        per_sign_semantic_rates.append(sign_repeats / sign_pairs if sign_pairs else 0.0)

    semantic_findings.sort(
        key=lambda item: (-item.similarity, item.sign, item.first_date, item.second_date)
    )
    semantic_near_repeat_rate = (
        semantic_repeat_count / semantic_review_pairs if semantic_review_pairs else 0.0
    )

    research_metrics = ResearchMetrics(
        avg_words=avg_words,
        avg_chars=avg_chars,
        max_words=max_words,
        max_caption_chars=max_caption_chars,
        daily_unique_ratio=fmean(daily_unique_ratios),
        lexical_diversity=lexical_diversity,
        unique_opening_ratio=unique_opening_ratio,
        topic_coverage_ratio=topic_coverage_ratio,
        topic_variety=topic_variety,
        topic_balance=topic_balance,
        actionable_ratio=actionable_ratio,
        temporal_diversity=fmean(temporal_diversities),
        distinct_text_ratio=fmean(distinct_ratios),
        min_distinct_texts_per_sign=min(distinct_counts),
        adjacent_repeat_rate=repeat_count / pair_count if pair_count else 0.0,
        semantic_review_days=semantic_review_days,
        semantic_review_cells=semantic_review_cells,
        semantic_review_pairs=semantic_review_pairs,
        semantic_near_repeat_rate=semantic_near_repeat_rate,
        max_semantic_near_repeat_rate_per_sign=max(per_sign_semantic_rates, default=0.0),
        max_semantic_similarity=max_semantic_similarity,
    )
    hard_gates = _hard_gates(research_metrics)
    quality_score = _quality_score(research_metrics)
    gates_passed = all(hard_gates.values())
    return ResearchEvaluation(
        numa_score=quality_score if gates_passed else 0.0,
        quality_score=quality_score,
        gates_passed=gates_passed,
        hard_gates=hard_gates,
        metrics=research_metrics,
        semantic_repeats=tuple(semantic_findings[:MAX_SEMANTIC_FINDINGS]),
    )


def _validate_snapshot_shape(snapshot: DailyHoroscopeSnapshot, forecast_date: date) -> None:
    if snapshot.forecast_date != forecast_date:
        raise ValueError("autoresearch candidate changed the requested forecast date")
    signs = tuple(item.sign for item in snapshot.signs)
    if signs != tuple(ZodiacSign):
        raise ValueError("autoresearch candidate must return every zodiac sign exactly once")


def _hard_gates(metrics: ResearchMetrics) -> dict[str, bool]:
    return {
        "telegram_caption_limit": metrics.max_caption_chars <= TELEGRAM_CAPTION_LIMIT,
        "daily_sign_copy_unique": math.isclose(metrics.daily_unique_ratio, 1.0),
        "no_adjacent_exact_repeat": math.isclose(metrics.adjacent_repeat_rate, 0.0),
        "minimum_temporal_diversity": metrics.temporal_diversity >= MIN_TEMPORAL_DIVERSITY,
        "minimum_distinct_copy_per_sign": (
            metrics.min_distinct_texts_per_sign >= MIN_DISTINCT_TEXTS_PER_SIGN
        ),
        "fourteen_day_semantic_repeat_rate": (
            metrics.semantic_near_repeat_rate <= MAX_SEMANTIC_NEAR_REPEAT_RATE
        ),
        "fourteen_day_per_sign_semantic_repeat_rate": (
            metrics.max_semantic_near_repeat_rate_per_sign
            <= MAX_SEMANTIC_NEAR_REPEAT_RATE_PER_SIGN
        ),
        "minimum_actionability": metrics.actionable_ratio >= MIN_ACTIONABLE_RATIO,
        "minimum_topic_coverage": metrics.topic_coverage_ratio >= MIN_TOPIC_COVERAGE_RATIO,
        "minimum_topic_variety": metrics.topic_variety >= MIN_TOPIC_VARIETY,
        "minimum_average_length": metrics.avg_words >= MIN_AVG_WORDS,
        "maximum_average_length": metrics.avg_words <= MAX_AVG_WORDS,
        "maximum_single_forecast_length": metrics.max_words <= MAX_FORECAST_WORDS,
    }


def _quality_score(metrics: ResearchMetrics) -> float:
    components = (
        20.0 * _saturating_ratio(metrics.actionable_ratio, 0.95),
        20.0 * _saturating_ratio(metrics.topic_coverage_ratio, 0.85),
        10.0 * _saturating_ratio(float(metrics.topic_variety), 8.0),
        10.0 * _saturating_ratio(metrics.lexical_diversity, 0.95),
        5.0 * _saturating_ratio(metrics.unique_opening_ratio, 0.95),
        15.0 * _saturating_ratio(metrics.temporal_diversity, 0.90),
        10.0 * _saturating_ratio(metrics.distinct_text_ratio, 0.35),
        10.0 * metrics.topic_balance,
    )
    return round(sum(components), 4)


def _normalized_entropy(counts: tuple[int, ...]) -> float:
    total = sum(counts)
    if total <= 0 or len(counts) <= 1:
        return 0.0
    probabilities = [count / total for count in counts]
    entropy = -sum(probability * math.log(probability) for probability in probabilities)
    return entropy / math.log(len(counts))


def _saturating_ratio(value: float, target: float) -> float:
    if target <= 0.0:
        raise ValueError("autoresearch score target must be positive")
    return min(max(value / target, 0.0), 1.0)


def _word_count(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in (match.casefold() for match in _TOKEN_RE.findall(text))
        if len(token) > 2 and token not in _TOKEN_STOPWORDS
    }


def _semantic_concepts(text: str) -> set[str]:
    lowered = text.casefold()
    return {
        concept
        for concept, roots in _SEMANTIC_CONCEPT_ROOTS.items()
        if any(root in lowered for root in roots)
    }


def _semantic_similarity(first: str, second: str) -> float:
    lexical_similarity = _jaccard(_tokens(first), _tokens(second))
    first_concepts = _semantic_concepts(first)
    second_concepts = _semantic_concepts(second)
    concept_similarity = (
        _jaccard(first_concepts, second_concepts)
        if len(first_concepts) >= 2 and len(second_concepts) >= 2
        else 0.0
    )
    return max(lexical_similarity, concept_similarity)


def _jaccard(first: set[str], second: set[str]) -> float:
    union = first | second
    if not union:
        return 1.0
    return len(first & second) / len(union)
