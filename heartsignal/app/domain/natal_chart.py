"""Versioned deterministic contracts for calculated natal chart facts."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

NATAL_CHART_SCHEMA_VERSION = "natal-chart-v1"
NATAL_CHART_ENGINE_VERSION = "astronomy-engine-2.1.19"
NATAL_CHART_HOUSE_SYSTEM = "equal-house-v1"


class NatalTimePrecision(StrEnum):
    EXACT = "exact"
    DATE_ONLY = "date_only"


class NatalBody(StrEnum):
    SUN = "sun"
    MOON = "moon"
    MERCURY = "mercury"
    VENUS = "venus"
    MARS = "mars"
    JUPITER = "jupiter"
    SATURN = "saturn"
    URANUS = "uranus"
    NEPTUNE = "neptune"
    PLUTO = "pluto"


class ZodiacSign(StrEnum):
    ARIES = "aries"
    TAURUS = "taurus"
    GEMINI = "gemini"
    CANCER = "cancer"
    LEO = "leo"
    VIRGO = "virgo"
    LIBRA = "libra"
    SCORPIO = "scorpio"
    SAGITTARIUS = "sagittarius"
    CAPRICORN = "capricorn"
    AQUARIUS = "aquarius"
    PISCES = "pisces"


class NatalAspectKind(StrEnum):
    CONJUNCTION = "conjunction"
    SEXTILE = "sextile"
    SQUARE = "square"
    TRINE = "trine"
    OPPOSITION = "opposition"


@dataclass(frozen=True, slots=True)
class NatalPlanetPosition:
    body: NatalBody
    longitude_millidegrees: int
    sign: ZodiacSign
    sign_degree_millidegrees: int
    retrograde: bool

    def __post_init__(self) -> None:
        if not 0 <= self.longitude_millidegrees < 360_000:
            raise ValueError("planet longitude must be between 0 and 360 degrees")
        if not 0 <= self.sign_degree_millidegrees < 30_000:
            raise ValueError("planet sign degree must be between 0 and 30 degrees")

    def payload(self) -> dict[str, object]:
        return {
            "body": self.body.value,
            "longitude_millidegrees": self.longitude_millidegrees,
            "sign": self.sign.value,
            "sign_degree_millidegrees": self.sign_degree_millidegrees,
            "retrograde": self.retrograde,
        }


@dataclass(frozen=True, slots=True)
class NatalAspect:
    first_body: NatalBody
    second_body: NatalBody
    kind: NatalAspectKind
    separation_millidegrees: int
    orb_millidegrees: int

    def __post_init__(self) -> None:
        if self.first_body.value >= self.second_body.value:
            raise ValueError("aspect bodies must use stable lexical ordering")
        if not 0 <= self.separation_millidegrees <= 180_000:
            raise ValueError("aspect separation must be between 0 and 180 degrees")
        if self.orb_millidegrees < 0:
            raise ValueError("aspect orb cannot be negative")

    def payload(self) -> dict[str, object]:
        return {
            "first_body": self.first_body.value,
            "second_body": self.second_body.value,
            "kind": self.kind.value,
            "separation_millidegrees": self.separation_millidegrees,
            "orb_millidegrees": self.orb_millidegrees,
        }


@dataclass(frozen=True, slots=True)
class NatalHouse:
    number: int
    cusp_longitude_millidegrees: int
    sign: ZodiacSign

    def __post_init__(self) -> None:
        if not 1 <= self.number <= 12:
            raise ValueError("house number must be between 1 and 12")
        if not 0 <= self.cusp_longitude_millidegrees < 360_000:
            raise ValueError("house cusp must be between 0 and 360 degrees")

    def payload(self) -> dict[str, object]:
        return {
            "number": self.number,
            "cusp_longitude_millidegrees": self.cusp_longitude_millidegrees,
            "sign": self.sign.value,
        }


@dataclass(frozen=True, slots=True)
class NatalChartResult:
    schema_version: str
    engine_version: str
    normalization_version: str
    time_precision: NatalTimePrecision
    calculation_utc: datetime
    calculation_assumption: str | None
    planets: tuple[NatalPlanetPosition, ...]
    aspects: tuple[NatalAspect, ...]
    houses: tuple[NatalHouse, ...]
    ascendant_longitude_millidegrees: int | None
    house_system: str | None

    def __post_init__(self) -> None:
        if self.schema_version != NATAL_CHART_SCHEMA_VERSION:
            raise ValueError("unsupported natal chart schema version")
        if self.engine_version != NATAL_CHART_ENGINE_VERSION:
            raise ValueError("unsupported natal chart engine version")
        if self.calculation_utc.tzinfo is None:
            raise ValueError("natal calculation time must be timezone-aware")
        if len(self.planets) != len(NatalBody):
            raise ValueError("natal chart must contain every supported body exactly once")
        if len({position.body for position in self.planets}) != len(self.planets):
            raise ValueError("natal chart contains duplicate bodies")
        if self.time_precision is NatalTimePrecision.EXACT:
            if self.calculation_assumption is not None:
                raise ValueError("exact natal chart cannot contain a time assumption")
            if self.ascendant_longitude_millidegrees is None:
                raise ValueError("exact natal chart requires an ascendant")
            if self.house_system != NATAL_CHART_HOUSE_SYSTEM or len(self.houses) != 12:
                raise ValueError("exact natal chart requires twelve equal houses")
        else:
            if self.calculation_assumption != "local_noon":
                raise ValueError("date-only natal chart must disclose local-noon assumption")
            if self.ascendant_longitude_millidegrees is not None:
                raise ValueError("date-only natal chart cannot contain an ascendant")
            if self.house_system is not None or self.houses:
                raise ValueError("date-only natal chart cannot contain houses")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "normalization_version": self.normalization_version,
            "time_precision": self.time_precision.value,
            "calculation_utc": self.calculation_utc.isoformat(),
            "calculation_assumption": self.calculation_assumption,
            "planets": [position.payload() for position in self.planets],
            "aspects": [aspect.payload() for aspect in self.aspects],
            "houses": [house.payload() for house in self.houses],
            "ascendant_longitude_millidegrees": self.ascendant_longitude_millidegrees,
            "house_system": self.house_system,
        }
