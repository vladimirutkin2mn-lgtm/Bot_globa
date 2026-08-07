"""Versioned calculated fact bundles and strict Horoscope output contracts."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints

from app.domain.natal_chart import (
    NATAL_CHART_HOUSE_SYSTEM,
    NatalAspectKind,
    NatalBody,
    ZodiacSign,
)
from app.domain.reading_result import (
    ReadingSafetyAssessment,
    ReadingScenario,
    ShareCardPayload,
    ShortText,
    StrictReadingResultModel,
    Text,
)

HOROSCOPE_FACTS_VERSION = "horoscope-facts-v1"
ASTROLOGY_READING_SCHEMA_VERSION = "astrology-reading-result-v1"
HOROSCOPE_RENDERER_VERSION = "horoscope-renderer-v1"

FactId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9:._-]+$",
    ),
]
Digest = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[0-9a-f]{64}$"),
]


class HoroscopeScope(StrEnum):
    NATAL_PROFILE = "natal_profile"
    WEEK_FORECAST = "week_forecast"
    MONTH_FORECAST = "month_forecast"
    DECISION = "decision"
    LOVE = "love"


class HoroscopeFactKind(StrEnum):
    NATAL_PLANET = "natal_planet"
    NATAL_ASPECT = "natal_aspect"
    NATAL_HOUSE = "natal_house"
    NATAL_ASCENDANT = "natal_ascendant"
    TRANSIT_PLANET = "transit_planet"
    TRANSIT_NATAL_ASPECT = "transit_natal_aspect"


class HoroscopeLimitation(StrEnum):
    ENTERTAINMENT_ONLY = "entertainment_only"
    BIRTH_TIME_UNKNOWN = "birth_time_unknown"
    SAMPLED_TRANSITS = "sampled_transits"
    NO_CERTAIN_PREDICTION = "no_certain_prediction"


_BODY_VALUES = frozenset(value.value for value in NatalBody)
_SIGN_VALUES = tuple(value.value for value in ZodiacSign)
_ASPECT_VALUES = frozenset(value.value for value in NatalAspectKind)
_ASPECT_ANGLES = {
    NatalAspectKind.CONJUNCTION.value: (0_000, 8_000),
    NatalAspectKind.SEXTILE.value: (60_000, 4_000),
    NatalAspectKind.SQUARE.value: (90_000, 6_000),
    NatalAspectKind.TRINE.value: (120_000, 6_000),
    NatalAspectKind.OPPOSITION.value: (180_000, 8_000),
}


@dataclass(frozen=True, slots=True)
class HoroscopeFact:
    fact_id: str
    kind: HoroscopeFactKind
    details: dict[str, object]

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z0-9:._-]{1,160}", self.fact_id) is None:
            raise ValueError("invalid horoscope fact id")
        if self.kind is HoroscopeFactKind.NATAL_PLANET:
            self._validate_planet(transit=False)
        elif self.kind is HoroscopeFactKind.TRANSIT_PLANET:
            self._validate_planet(transit=True)
        elif self.kind is HoroscopeFactKind.NATAL_ASPECT:
            self._validate_natal_aspect()
        elif self.kind is HoroscopeFactKind.NATAL_HOUSE:
            self._validate_house()
        elif self.kind is HoroscopeFactKind.NATAL_ASCENDANT:
            self._validate_ascendant()
        elif self.kind is HoroscopeFactKind.TRANSIT_NATAL_ASPECT:
            self._validate_transit_aspect()
        else:
            raise ValueError("unsupported horoscope fact kind")

    def payload(self) -> dict[str, object]:
        return {
            "fact_id": self.fact_id,
            "kind": self.kind.value,
            "details": self.details,
        }

    def _validate_planet(self, *, transit: bool) -> None:
        expected = {
            "body",
            "longitude_millidegrees",
            "sign",
            "sign_degree_millidegrees",
            "retrograde",
        }
        if transit:
            expected.add("sample_date")
        self._require_exact_keys(expected)
        body = self._require_member("body", _BODY_VALUES)
        longitude = self._require_int("longitude_millidegrees", 0, 359_999)
        sign = self._require_member("sign", frozenset(_SIGN_VALUES))
        sign_degree = self._require_int("sign_degree_millidegrees", 0, 29_999)
        self._require_bool("retrograde")
        if sign != _SIGN_VALUES[longitude // 30_000] or sign_degree != longitude % 30_000:
            raise ValueError("horoscope planet sign fields do not match longitude")
        if transit:
            sample_date = self._require_date("sample_date")
            expected_id = f"transit:{sample_date}:planet:{body}"
        else:
            expected_id = f"natal:planet:{body}"
        self._require_fact_id(expected_id)

    def _validate_natal_aspect(self) -> None:
        self._require_exact_keys(
            {
                "first_body",
                "second_body",
                "kind",
                "separation_millidegrees",
                "orb_millidegrees",
            }
        )
        first = self._require_member("first_body", _BODY_VALUES)
        second = self._require_member("second_body", _BODY_VALUES)
        kind = self._require_member("kind", _ASPECT_VALUES)
        if first >= second:
            raise ValueError("horoscope natal aspect bodies must use lexical ordering")
        self._validate_aspect_angles(kind)
        self._require_fact_id(f"natal:aspect:{first}:{second}:{kind}")

    def _validate_house(self) -> None:
        self._require_exact_keys({"number", "cusp_longitude_millidegrees", "sign"})
        number = self._require_int("number", 1, 12)
        longitude = self._require_int("cusp_longitude_millidegrees", 0, 359_999)
        sign = self._require_member("sign", frozenset(_SIGN_VALUES))
        if sign != _SIGN_VALUES[longitude // 30_000]:
            raise ValueError("horoscope house sign does not match cusp longitude")
        self._require_fact_id(f"natal:house:{number}")

    def _validate_ascendant(self) -> None:
        self._require_exact_keys(
            {
                "longitude_millidegrees",
                "sign",
                "sign_degree_millidegrees",
                "house_system",
            }
        )
        longitude = self._require_int("longitude_millidegrees", 0, 359_999)
        sign = self._require_member("sign", frozenset(_SIGN_VALUES))
        sign_degree = self._require_int("sign_degree_millidegrees", 0, 29_999)
        house_system = self._require_text("house_system")
        if house_system != NATAL_CHART_HOUSE_SYSTEM:
            raise ValueError("unsupported horoscope house system")
        if sign != _SIGN_VALUES[longitude // 30_000] or sign_degree != longitude % 30_000:
            raise ValueError("horoscope ascendant sign fields do not match longitude")
        self._require_fact_id("natal:ascendant")

    def _validate_transit_aspect(self) -> None:
        self._require_exact_keys(
            {
                "sample_date",
                "transit_body",
                "natal_body",
                "kind",
                "separation_millidegrees",
                "orb_millidegrees",
            }
        )
        sample_date = self._require_date("sample_date")
        transit_body = self._require_member("transit_body", _BODY_VALUES)
        natal_body = self._require_member("natal_body", _BODY_VALUES)
        kind = self._require_member("kind", _ASPECT_VALUES)
        self._validate_aspect_angles(kind)
        self._require_fact_id(f"transit:{sample_date}:{transit_body}:natal:{natal_body}:{kind}")

    def _validate_aspect_angles(self, kind: str) -> None:
        separation = self._require_int("separation_millidegrees", 0, 180_000)
        orb = self._require_int("orb_millidegrees", 0, 8_000)
        exact_angle, maximum_orb = _ASPECT_ANGLES[kind]
        if orb > maximum_orb or abs(separation - exact_angle) != orb:
            raise ValueError("horoscope aspect orb does not match separation")

    def _require_exact_keys(self, expected: set[str]) -> None:
        if set(self.details) != expected:
            raise ValueError("invalid horoscope fact detail fields")

    def _require_fact_id(self, expected: str) -> None:
        if self.fact_id != expected:
            raise ValueError("horoscope fact id does not match details")

    def _require_text(self, key: str) -> str:
        value = self.details.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError("invalid horoscope fact text field")
        return value

    def _require_member(self, key: str, allowed: frozenset[str]) -> str:
        value = self._require_text(key)
        if value not in allowed:
            raise ValueError("unsupported horoscope fact enum value")
        return value

    def _require_int(self, key: str, minimum: int, maximum: int) -> int:
        value = self.details.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("invalid horoscope fact integer field")
        if not minimum <= value <= maximum:
            raise ValueError("horoscope fact integer field is out of range")
        return value

    def _require_bool(self, key: str) -> bool:
        value = self.details.get(key)
        if not isinstance(value, bool):
            raise ValueError("invalid horoscope fact boolean field")
        return value

    def _require_date(self, key: str) -> str:
        value = self._require_text(key)
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("invalid horoscope fact date field") from exc
        if parsed.isoformat() != value:
            raise ValueError("horoscope fact date must use ISO format")
        return value


@dataclass(frozen=True, slots=True)
class HoroscopeFactBundle:
    facts_version: str
    scope: HoroscopeScope
    calculated_at_utc: datetime
    period_start: date | None
    period_end: date | None
    natal_schema_version: str
    natal_engine_version: str
    facts: tuple[HoroscopeFact, ...]
    limitations: tuple[HoroscopeLimitation, ...]

    def __post_init__(self) -> None:
        if self.facts_version != HOROSCOPE_FACTS_VERSION:
            raise ValueError("unsupported horoscope facts version")
        if self.calculated_at_utc.tzinfo is None:
            raise ValueError("horoscope calculation time must be timezone-aware")
        if self.scope in {HoroscopeScope.WEEK_FORECAST, HoroscopeScope.MONTH_FORECAST}:
            if self.period_start is None or self.period_end is None:
                raise ValueError("forecast fact bundle requires a period")
            if self.period_end < self.period_start:
                raise ValueError("forecast period cannot end before it starts")
        elif self.period_start is not None or self.period_end is not None:
            raise ValueError("non-forecast fact bundle cannot contain a period")
        fact_ids = [fact.fact_id for fact in self.facts]
        if not fact_ids:
            raise ValueError("horoscope fact bundle cannot be empty")
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("horoscope fact ids must be unique")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("horoscope limitations must be unique")
        if HoroscopeLimitation.ENTERTAINMENT_ONLY not in self.limitations:
            raise ValueError("horoscope facts must disclose entertainment-only use")
        if HoroscopeLimitation.NO_CERTAIN_PREDICTION not in self.limitations:
            raise ValueError("horoscope facts must prohibit certain prediction")
        has_houses = any(
            fact.kind in {HoroscopeFactKind.NATAL_HOUSE, HoroscopeFactKind.NATAL_ASCENDANT}
            for fact in self.facts
        )
        if HoroscopeLimitation.BIRTH_TIME_UNKNOWN in self.limitations and has_houses:
            raise ValueError("unknown birth time cannot contain house or ascendant facts")
        has_transits = any(
            fact.kind
            in {
                HoroscopeFactKind.TRANSIT_PLANET,
                HoroscopeFactKind.TRANSIT_NATAL_ASPECT,
            }
            for fact in self.facts
        )
        if has_transits != (HoroscopeLimitation.SAMPLED_TRANSITS in self.limitations):
            raise ValueError("sampled transit limitation must match transit facts")
        if has_transits != (self.period_start is not None):
            raise ValueError("transit facts require a forecast period")

    @property
    def fact_ids(self) -> frozenset[str]:
        return frozenset(fact.fact_id for fact in self.facts)

    def fact_by_id(self, fact_id: str) -> HoroscopeFact | None:
        return next((fact for fact in self.facts if fact.fact_id == fact_id), None)

    def payload(self) -> dict[str, object]:
        return {
            "facts_version": self.facts_version,
            "scope": self.scope.value,
            "calculated_at_utc": self.calculated_at_utc.astimezone(UTC).isoformat(),
            "period_start": None if self.period_start is None else self.period_start.isoformat(),
            "period_end": None if self.period_end is None else self.period_end.isoformat(),
            "natal_schema_version": self.natal_schema_version,
            "natal_engine_version": self.natal_engine_version,
            "facts": [fact.payload() for fact in self.facts],
            "limitations": [value.value for value in self.limitations],
        }

    def digest(self) -> str:
        canonical = json.dumps(
            self.payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


class AstrologyInterpretation(StrictReadingResultModel):
    fact_ids: list[FactId] = Field(min_length=1, max_length=6)
    text: Text


class AstrologyReadingResult(StrictReadingResultModel):
    title: ShortText
    scope: HoroscopeScope
    facts_digest: Digest
    overview: Text
    interpretations: list[AstrologyInterpretation] = Field(min_length=1, max_length=10)
    themes: list[Text] = Field(min_length=1, max_length=7)
    possible_scenarios: list[ReadingScenario] = Field(min_length=1, max_length=5)
    reflection_questions: list[Text] = Field(max_length=5)
    practical_step: Text
    limitations: list[HoroscopeLimitation] = Field(min_length=2, max_length=6)
    uncertainty_note: Text
    share_card: ShareCardPayload
    safety: ReadingSafetyAssessment


class AstrologyReadingSemanticError(ValueError):
    """Safe semantic error containing field locations but no generated content."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__(";".join(issues))


_RAW_ASTROLOGY_TERM = re.compile(
    r"\b(?:sun|moon|mercury|venus|mars|jupiter|saturn|uranus|neptune|pluto|"
    r"aries|taurus|gemini|cancer|leo|virgo|libra|scorpio|sagittarius|"
    r"capricorn|aquarius|pisces|ascendant|house\s*(?:[1-9]|1[0-2])|"
    r"солнц[еа]|лун[аы]|меркури[йя]|венер[аы]|марс[а]?|юпитер[а]?|сатурн[а]?|"  # noqa: RUF001
    r"уран[а]?|нептун[а]?|плутон[а]?|овен|телец|близнец(?:ы|ов)|рак|лев|дева|"  # noqa: RUF001
    r"весы|скорпион|стрелец|козерог|водолей|рыбы|асцендент|дом\s*(?:[1-9]|1[0-2]))\b",
    re.IGNORECASE,
)
_RAW_DEGREE_CLAIM = re.compile(
    r"\b\d{1,3}(?:[.,]\d+)?\s*(?:°|degrees?|deg\.?|градус(?:а|ов)?)\b",  # noqa: RUF001
    re.IGNORECASE,
)


def validate_astrology_reading_semantics(
    result: AstrologyReadingResult,
    expected: HoroscopeFactBundle,
) -> None:
    """Bind model prose to application facts and forbid model-authored chart positions."""

    issues: list[str] = []
    if result.scope is not expected.scope:
        issues.append("scope:mismatch")
    if result.facts_digest != expected.digest():
        issues.append("facts_digest:mismatch")
    if not set(expected.limitations).issubset(result.limitations):
        issues.append("limitations:missing_required")
    if len(result.limitations) != len(set(result.limitations)):
        issues.append("limitations:duplicate")
    for index, interpretation in enumerate(result.interpretations):
        if len(interpretation.fact_ids) != len(set(interpretation.fact_ids)):
            issues.append(f"interpretations.{index}.fact_ids:duplicate")
        if any(fact_id not in expected.fact_ids for fact_id in interpretation.fact_ids):
            issues.append(f"interpretations.{index}.fact_ids:unknown")
    if result.safety.high_risk_detected != bool(result.safety.categories):
        issues.append("safety:inconsistent_risk_flag")
    for path, value in _visible_astrology_texts(result):
        if _RAW_ASTROLOGY_TERM.search(value):
            issues.append(f"{path}:raw_astrology_claim")
        if _RAW_DEGREE_CLAIM.search(value):
            issues.append(f"{path}:raw_degree_claim")
    if issues:
        raise AstrologyReadingSemanticError(list(dict.fromkeys(issues)))


def visible_astrology_texts(result: AstrologyReadingResult) -> tuple[tuple[str, str], ...]:
    """Return every user-visible narrative field for deterministic safety validation."""

    return _visible_astrology_texts(result)


def _visible_astrology_texts(result: AstrologyReadingResult) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = [
        ("title", result.title),
        ("overview", result.overview),
    ]
    values.extend(
        (f"interpretations.{index}.text", item.text)
        for index, item in enumerate(result.interpretations)
    )
    values.extend((f"themes.{index}", value) for index, value in enumerate(result.themes))
    for scenario_index, scenario in enumerate(result.possible_scenarios):
        values.append((f"possible_scenarios.{scenario_index}.scenario", scenario.scenario))
        values.extend(
            (
                f"possible_scenarios.{scenario_index}.conditions.{condition_index}",
                condition,
            )
            for condition_index, condition in enumerate(scenario.conditions)
        )
    values.extend(
        (f"reflection_questions.{index}", value)
        for index, value in enumerate(result.reflection_questions)
    )
    values.extend(
        (
            ("practical_step", result.practical_step),
            ("uncertainty_note", result.uncertainty_note),
            ("share_card.headline", result.share_card.headline),
            ("share_card.short_text", result.share_card.short_text),
        )
    )
    return tuple(values)
