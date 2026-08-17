"""Deterministic astrological compatibility from two consented natal charts."""

from dataclasses import dataclass
from enum import StrEnum

from app.domain.natal_chart import NatalBody, NatalChartResult, NatalPlanetPosition, ZodiacSign


class CompatibilityContext(StrEnum):
    LOVE = "love"
    FRIENDSHIP = "friend"
    WORK = "work"
    TRAVEL = "travel"


@dataclass(frozen=True, slots=True)
class SynastryScores:
    attraction: int
    communication: int
    emotional: int
    stability: int


@dataclass(frozen=True, slots=True)
class SynastryResult:
    context: CompatibilityContext
    overall: int
    scores: SynastryScores
    strongest: str
    weakest: str
    verdict: str


_ELEMENTS: dict[ZodiacSign, str] = {
    ZodiacSign.ARIES: "fire",
    ZodiacSign.LEO: "fire",
    ZodiacSign.SAGITTARIUS: "fire",
    ZodiacSign.TAURUS: "earth",
    ZodiacSign.VIRGO: "earth",
    ZodiacSign.CAPRICORN: "earth",
    ZodiacSign.GEMINI: "air",
    ZodiacSign.LIBRA: "air",
    ZodiacSign.AQUARIUS: "air",
    ZodiacSign.CANCER: "water",
    ZodiacSign.SCORPIO: "water",
    ZodiacSign.PISCES: "water",
}
_MODALITIES: dict[ZodiacSign, str] = {
    ZodiacSign.ARIES: "cardinal",
    ZodiacSign.CANCER: "cardinal",
    ZodiacSign.LIBRA: "cardinal",
    ZodiacSign.CAPRICORN: "cardinal",
    ZodiacSign.TAURUS: "fixed",
    ZodiacSign.LEO: "fixed",
    ZodiacSign.SCORPIO: "fixed",
    ZodiacSign.AQUARIUS: "fixed",
    ZodiacSign.GEMINI: "mutable",
    ZodiacSign.VIRGO: "mutable",
    ZodiacSign.SAGITTARIUS: "mutable",
    ZodiacSign.PISCES: "mutable",
}
_COMPLEMENTARY_ELEMENTS = {frozenset(("fire", "air")), frozenset(("earth", "water"))}

_DIMENSION_NAMES = {
    "attraction": "притяжение",
    "communication": "общение",
    "emotional": "эмоциональный ритм",
    "stability": "потенциал в долгую",
}
_CONTEXT_WEIGHTS: dict[CompatibilityContext, tuple[float, float, float, float]] = {
    CompatibilityContext.LOVE: (0.35, 0.20, 0.25, 0.20),
    CompatibilityContext.FRIENDSHIP: (0.10, 0.35, 0.25, 0.30),
    CompatibilityContext.WORK: (0.05, 0.40, 0.15, 0.40),
    CompatibilityContext.TRAVEL: (0.15, 0.30, 0.20, 0.35),
}

PairSpec = tuple[NatalBody, NatalBody, float]
_ATTRACTION_PAIRS: tuple[PairSpec, ...] = (
    (NatalBody.VENUS, NatalBody.MARS, 1.4),
    (NatalBody.MARS, NatalBody.VENUS, 1.4),
    (NatalBody.VENUS, NatalBody.VENUS, 1.0),
    (NatalBody.MARS, NatalBody.MARS, 0.7),
    (NatalBody.SUN, NatalBody.VENUS, 0.8),
    (NatalBody.VENUS, NatalBody.SUN, 0.8),
)
_COMMUNICATION_PAIRS: tuple[PairSpec, ...] = (
    (NatalBody.MERCURY, NatalBody.MERCURY, 1.5),
    (NatalBody.MERCURY, NatalBody.SUN, 0.9),
    (NatalBody.SUN, NatalBody.MERCURY, 0.9),
    (NatalBody.MERCURY, NatalBody.MOON, 0.8),
    (NatalBody.MOON, NatalBody.MERCURY, 0.8),
)
_EMOTIONAL_PAIRS: tuple[PairSpec, ...] = (
    (NatalBody.MOON, NatalBody.MOON, 1.5),
    (NatalBody.MOON, NatalBody.VENUS, 1.0),
    (NatalBody.VENUS, NatalBody.MOON, 1.0),
    (NatalBody.SUN, NatalBody.MOON, 0.8),
    (NatalBody.MOON, NatalBody.SUN, 0.8),
    (NatalBody.SUN, NatalBody.VENUS, 0.5),
    (NatalBody.VENUS, NatalBody.SUN, 0.5),
)
_STABILITY_PAIRS: tuple[PairSpec, ...] = (
    (NatalBody.SUN, NatalBody.SUN, 0.8),
    (NatalBody.VENUS, NatalBody.VENUS, 1.2),
    (NatalBody.SATURN, NatalBody.SUN, 1.0),
    (NatalBody.SUN, NatalBody.SATURN, 1.0),
    (NatalBody.SATURN, NatalBody.VENUS, 1.0),
    (NatalBody.VENUS, NatalBody.SATURN, 1.0),
    (NatalBody.MOON, NatalBody.MOON, 0.8),
)

_ASPECT_EFFECTS: dict[str, dict[int, float]] = {
    "attraction": {0: 7.0, 60: 4.0, 90: 3.0, 120: 7.0, 180: 5.0},
    "communication": {0: 5.0, 60: 5.0, 90: -6.0, 120: 7.0, 180: -3.0},
    "emotional": {0: 4.0, 60: 5.0, 90: -6.0, 120: 8.0, 180: -4.0},
    "stability": {0: 3.0, 60: 5.0, 90: -7.0, 120: 7.0, 180: -5.0},
}
_ASPECT_ORBS = {0: 8_000, 60: 5_000, 90: 6_000, 120: 6_000, 180: 8_000}


def calculate_synastry(
    first: NatalChartResult,
    second: NatalChartResult,
    context: CompatibilityContext,
) -> SynastryResult:
    """Score cross-chart planetary geometry without an LLM or random input."""

    first_positions = {position.body: position for position in first.planets}
    second_positions = {position.body: position for position in second.planets}
    scores = SynastryScores(
        attraction=_dimension_score(
            "attraction", first_positions, second_positions, _ATTRACTION_PAIRS
        ),
        communication=_dimension_score(
            "communication", first_positions, second_positions, _COMMUNICATION_PAIRS
        ),
        emotional=_dimension_score(
            "emotional", first_positions, second_positions, _EMOTIONAL_PAIRS
        ),
        stability=_dimension_score(
            "stability", first_positions, second_positions, _STABILITY_PAIRS
        ),
    )
    values = {
        "attraction": scores.attraction,
        "communication": scores.communication,
        "emotional": scores.emotional,
        "stability": scores.stability,
    }
    weights = _CONTEXT_WEIGHTS[context]
    overall = round(
        sum(
            value * weight
            for value, weight in zip(values.values(), weights, strict=True)
        )
    )
    strongest_key = max(values, key=values.__getitem__)
    weakest_key = min(values, key=values.__getitem__)
    return SynastryResult(
        context=context,
        overall=overall,
        scores=scores,
        strongest=_DIMENSION_NAMES[strongest_key],
        weakest=_DIMENSION_NAMES[weakest_key],
        verdict=_verdict(overall, context),
    )


def _dimension_score(
    dimension: str,
    first: dict[NatalBody, NatalPlanetPosition],
    second: dict[NatalBody, NatalPlanetPosition],
    pairs: tuple[PairSpec, ...],
) -> int:
    weighted_total = 0.0
    total_weight = 0.0
    for first_body, second_body, weight in pairs:
        first_position = first[first_body]
        second_position = second[second_body]
        contribution = _sign_compatibility(first_position.sign, second_position.sign)
        contribution += _aspect_effect(dimension, first_position, second_position)
        weighted_total += contribution * weight
        total_weight += weight
    raw = 62.0 + 2.05 * (weighted_total / total_weight)
    return max(38, min(96, round(raw)))


def _sign_compatibility(first: ZodiacSign, second: ZodiacSign) -> float:
    if first is second:
        base = 7.0
    else:
        first_element = _ELEMENTS[first]
        second_element = _ELEMENTS[second]
        if first_element == second_element:
            base = 8.0
        elif frozenset((first_element, second_element)) in _COMPLEMENTARY_ELEMENTS:
            base = 5.0
        else:
            base = -3.0
    if _MODALITIES[first] == _MODALITIES[second] and first is not second:
        base -= 1.5
    return base


def _aspect_effect(
    dimension: str,
    first: NatalPlanetPosition,
    second: NatalPlanetPosition,
) -> float:
    separation = abs(first.longitude_millidegrees - second.longitude_millidegrees)
    separation = min(separation, 360_000 - separation)
    angle = min(_ASPECT_ORBS, key=lambda candidate: abs(separation - candidate * 1_000))
    orb = abs(separation - angle * 1_000)
    maximum_orb = _ASPECT_ORBS[angle]
    if orb > maximum_orb:
        return 0.0
    closeness = 1.0 - orb / maximum_orb
    return _ASPECT_EFFECTS[dimension][angle] * closeness


def _verdict(overall: int, context: CompatibilityContext) -> str:
    noun = {
        CompatibilityContext.LOVE: "между вами",
        CompatibilityContext.FRIENDSHIP: "в этой дружбе",
        CompatibilityContext.WORK: "в этой связке",
        CompatibilityContext.TRAVEL: "в вашей поездке",
    }[context]
    if overall >= 84:
        return (
            f"{noun.capitalize()} слишком много совпадений, "
            "чтобы всё прошло незаметно."
        )
    if overall >= 74:
        return (
            f"{noun.capitalize()} сильная база — искры и споры "
            "вполне могут идти комплектом."
        )
    if overall >= 64:
        return (
            f"{noun.capitalize()} всё работает лучше, "
            "когда вы не пытаетесь быть одинаковыми."
        )
    if overall >= 54:
        return (
            f"{noun.capitalize()} есть сюжет, но инструкция "
            "по эксплуатации точно пригодится."
        )
    return (
        f"{noun.capitalize()} звёзды обещают не лёгкость, "
        "а очень нескучный сюжет."
    )
