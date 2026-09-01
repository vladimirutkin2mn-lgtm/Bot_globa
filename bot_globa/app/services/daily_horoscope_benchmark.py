"""Derived-metric benchmark helpers for mass daily horoscopes.

The benchmark intentionally does not persist or republish third-party horoscope copy.
Fetched reference text is processed in memory into aggregate metrics and one-way hashes.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from itertools import combinations
from statistics import fmean
from types import MappingProxyType
from typing import Sequence

from app.domain.natal_chart import ZodiacSign

_TOKEN_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[.!?]+")
_WHITESPACE_RE = re.compile(r"\s+")
_ORAKUL_HEADING_RE = re.compile(
    r"^Общий гороскоп на (?:сегодня|вчера|завтра),\s+",
    re.IGNORECASE,
)

_STOPWORDS = frozenset(
    {
        "без",
        "бы",
        "был",
        "была",
        "были",
        "вам",
        "вас",
        "ваш",
        "ваша",
        "ваше",
        "ваши",
        "вы",
        "для",
        "его",
        "если",
        "еще",
        "же",
        "как",
        "на",
        "не",
        "но",
        "она",
        "они",
        "оно",
        "от",
        "по",
        "при",
        "свою",
        "свои",
        "свой",
        "себе",
        "себя",
        "так",
        "то",
        "уже",
        "что",
        "это",
        "этот",
        "эта",
        "этом",
    }
)

_TOPIC_KEYWORDS = MappingProxyType(
    {
        "relationships": (
            "отношен",
            "партнер",
            "партнёр",
            "любов",
            "любим",
            "симпат",
            "роман",
            "половинк",
            "свидан",
        ),
        "money": (
            "деньг",
            "финанс",
            "доход",
            "расход",
            "покуп",
            "бюджет",
            "зарплат",
            "долг",
        ),
        "career_work": (
            "работ",
            "карьер",
            "коллег",
            "началь",
            "проект",
            "делов",
            "професс",
            "задач",
        ),
        "home_family": (
            "семь",
            "дом",
            "близк",
            "родител",
            "родствен",
            "ребен",
            "ребён",
            "быт",
        ),
        "communication": (
            "разговор",
            "общен",
            "общён",
            "переписк",
            "сообщен",
            "сообщён",
            "новост",
            "вопрос",
            "ответ",
        ),
        "health_energy": (
            "здоров",
            "самочув",
            "энерг",
            "устал",
            "отдых",
            "сон",
            "сил",
        ),
        "travel_learning": (
            "поезд",
            "путеше",
            "дорог",
            "обуч",
            "учеб",
            "знан",
            "информац",
        ),
        "plans_action": (
            "план",
            "решен",
            "решён",
            "решит",
            "шаг",
            "действ",
            "цель",
            "выбор",
            "возможност",
        ),
    }
)

_ACTION_MARKERS = (
    "лучше ",
    "стоит ",
    "не стоит ",
    "постарай",
    "сделай",
    "сделайте",
    "проверь",
    "обсуд",
    "поговор",
    "реши",
    "решите",
    "обрат",
    "удел",
    "не спеш",
    "выберите",
    "сосредоточ",
)


@dataclass(frozen=True, slots=True)
class BenchmarkForecast:
    sign: ZodiacSign
    text: str


@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    forecast_count: int
    avg_chars: float
    avg_words: float
    avg_sentences: float
    lexical_diversity: float
    unique_opening_ratio: float
    topic_coverage_ratio: float
    topic_variety: int
    actionable_ratio: float
    topic_distribution: dict[str, int]

    def payload(self) -> dict[str, object]:
        return {
            "forecast_count": self.forecast_count,
            "avg_chars": round(self.avg_chars, 2),
            "avg_words": round(self.avg_words, 2),
            "avg_sentences": round(self.avg_sentences, 2),
            "lexical_diversity": round(self.lexical_diversity, 4),
            "unique_opening_ratio": round(self.unique_opening_ratio, 4),
            "topic_coverage_ratio": round(self.topic_coverage_ratio, 4),
            "topic_variety": self.topic_variety,
            "actionable_ratio": round(self.actionable_ratio, 4),
            "topic_distribution": dict(sorted(self.topic_distribution.items())),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkSourceSummary:
    source: str
    metrics: BenchmarkMetrics
    fingerprints: dict[str, str]

    def payload(self) -> dict[str, object]:
        return {
            "source": self.source,
            "metrics": self.metrics.payload(),
            "fingerprints": dict(sorted(self.fingerprints.items())),
        }


class _VisibleTextParser(HTMLParser):
    _BLOCK_TAGS = frozenset(
        {
            "article",
            "br",
            "div",
            "h1",
            "h2",
            "h3",
            "li",
            "main",
            "p",
            "section",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth == 0 and tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth == 0 and tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self._parts.append(data)

    def lines(self) -> list[str]:
        raw = "".join(self._parts)
        return [
            collapsed
            for line in raw.splitlines()
            if (collapsed := _WHITESPACE_RE.sub(" ", line).strip())
        ]


def extract_orakul_general_forecast(html: str) -> str:
    """Extract only the visible general forecast body from one Orakul sign page."""

    parser = _VisibleTextParser()
    parser.feed(html)
    lines = parser.lines()
    heading_index = next(
        (index for index, line in enumerate(lines) if _ORAKUL_HEADING_RE.match(line)),
        None,
    )
    if heading_index is None:
        raise ValueError("Orakul general horoscope heading not found")

    stop_markers = {
        "Подробнее",
        "Читать дальше",
        "Вернуться на главную раздела",
        "Поделиться в соцсетях",
        "Хочу получать рассылку",
    }
    forecast_lines: list[str] = []
    for line in lines[heading_index + 1 :]:
        if line in stop_markers:
            break
        forecast_lines.append(line)

    text = _WHITESPACE_RE.sub(" ", " ".join(forecast_lines)).strip()
    if len(text) < 20:
        raise ValueError("Orakul general horoscope body not found")
    return text


def build_benchmark_metrics(forecasts: Sequence[BenchmarkForecast]) -> BenchmarkMetrics:
    if not forecasts:
        raise ValueError("at least one forecast is required")
    if len({item.sign for item in forecasts}) != len(forecasts):
        raise ValueError("benchmark forecasts contain duplicate zodiac signs")

    texts = [item.text.strip() for item in forecasts]
    if any(not text for text in texts):
        raise ValueError("benchmark forecast text must not be empty")

    tokens = [_significant_tokens(text) for text in texts]
    sentence_counts = [max(1, len(_SENTENCE_RE.findall(text))) for text in texts]
    topics = [_classify_topic(text) for text in texts]

    topic_distribution: dict[str, int] = {}
    for topic in topics:
        topic_distribution[topic] = topic_distribution.get(topic, 0) + 1

    pair_overlaps = [_jaccard(set(first), set(second)) for first, second in combinations(tokens, 2)]
    lexical_diversity = 1.0 - (fmean(pair_overlaps) if pair_overlaps else 0.0)

    openings = {tuple(significant[:4]) for significant in tokens if significant}
    unique_opening_ratio = len(openings) / len(texts)

    covered = sum(topic != "other" for topic in topics)
    actionable = sum(_is_actionable(text) for text in texts)
    topic_variety = len({topic for topic in topics if topic != "other"})

    return BenchmarkMetrics(
        forecast_count=len(texts),
        avg_chars=fmean(len(text) for text in texts),
        avg_words=fmean(len(_TOKEN_RE.findall(text)) for text in texts),
        avg_sentences=fmean(sentence_counts),
        lexical_diversity=lexical_diversity,
        unique_opening_ratio=unique_opening_ratio,
        topic_coverage_ratio=covered / len(texts),
        topic_variety=topic_variety,
        actionable_ratio=actionable / len(texts),
        topic_distribution=topic_distribution,
    )


def build_source_summary(
    source: str,
    forecasts: Sequence[BenchmarkForecast],
) -> BenchmarkSourceSummary:
    fingerprints = {
        item.sign.value: hashlib.sha256(_normalize_for_hash(item.text).encode("utf-8")).hexdigest()
        for item in forecasts
    }
    return BenchmarkSourceSummary(
        source=source,
        metrics=build_benchmark_metrics(forecasts),
        fingerprints=fingerprints,
    )


def compare_source_summaries(
    numa: BenchmarkSourceSummary,
    reference: BenchmarkSourceSummary,
) -> dict[str, object]:
    """Return derived gaps and human-readable signals without exposing source copy."""

    n = numa.metrics
    r = reference.metrics
    gaps = {
        "avg_words_ratio": _safe_ratio(n.avg_words, r.avg_words),
        "avg_sentences_ratio": _safe_ratio(n.avg_sentences, r.avg_sentences),
        "lexical_diversity_gap": n.lexical_diversity - r.lexical_diversity,
        "unique_opening_ratio_gap": n.unique_opening_ratio - r.unique_opening_ratio,
        "topic_coverage_ratio_gap": n.topic_coverage_ratio - r.topic_coverage_ratio,
        "topic_variety_gap": n.topic_variety - r.topic_variety,
        "actionable_ratio_gap": n.actionable_ratio - r.actionable_ratio,
    }

    signals: list[str] = []
    if n.avg_words < r.avg_words * 0.7:
        signals.append("Numa forecasts are materially shorter than the reference.")
    if n.lexical_diversity + 0.05 < r.lexical_diversity:
        signals.append("Numa has lower cross-sign lexical diversity than the reference.")
    if n.topic_variety < r.topic_variety:
        signals.append("Numa covers fewer distinct life topics than the reference.")
    if n.actionable_ratio + 0.1 < r.actionable_ratio:
        signals.append("Numa gives an actionable next step less often than the reference.")
    if not signals:
        signals.append("No material quality gap was detected on the tracked benchmark metrics.")

    return {
        "numa": numa.payload(),
        "reference": reference.payload(),
        "gaps": {key: round(value, 4) for key, value in gaps.items()},
        "signals": signals,
    }


def _significant_tokens(text: str) -> list[str]:
    return [
        token
        for token in (match.casefold() for match in _TOKEN_RE.findall(text))
        if len(token) > 2 and token not in _STOPWORDS
    ]


def _classify_topic(text: str) -> str:
    lowered = text.casefold()
    scores = {
        topic: sum(keyword in lowered for keyword in keywords)
        for topic, keywords in _TOPIC_KEYWORDS.items()
    }
    topic, score = max(scores.items(), key=lambda item: item[1])
    return topic if score > 0 else "other"


def _is_actionable(text: str) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in _ACTION_MARKERS)


def _jaccard(first: set[str], second: set[str]) -> float:
    if not first and not second:
        return 1.0
    union = first | second
    if not union:
        return 0.0
    return len(first & second) / len(union)


def _normalize_for_hash(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip().casefold()


def _safe_ratio(value: float, reference: float) -> float:
    if math.isclose(reference, 0.0):
        return 0.0 if math.isclose(value, 0.0) else 1.0
    return value / reference
