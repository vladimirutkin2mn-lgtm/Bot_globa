"""Deterministic natal and sampled-transit facts for Horoscope generation."""

import calendar
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from uuid import UUID

import astronomy

from app.domain.horoscope import (
    HOROSCOPE_FACTS_VERSION,
    HoroscopeFact,
    HoroscopeFactBundle,
    HoroscopeFactKind,
    HoroscopeLimitation,
    HoroscopeScope,
)
from app.domain.natal_chart import (
    NatalAspectKind,
    NatalBody,
    NatalChartResult,
    NatalTimePrecision,
    ZodiacSign,
)

_TRANSIT_BODIES: tuple[tuple[NatalBody, Any], ...] = (
    (NatalBody.SUN, astronomy.Body.Sun),
    (NatalBody.MOON, astronomy.Body.Moon),
    (NatalBody.MERCURY, astronomy.Body.Mercury),
    (NatalBody.VENUS, astronomy.Body.Venus),
    (NatalBody.MARS, astronomy.Body.Mars),
    (NatalBody.JUPITER, astronomy.Body.Jupiter),
    (NatalBody.SATURN, astronomy.Body.Saturn),
    (NatalBody.URANUS, astronomy.Body.Uranus),
    (NatalBody.NEPTUNE, astronomy.Body.Neptune),
    (NatalBody.PLUTO, astronomy.Body.Pluto),
)
_ASPECTS: tuple[tuple[NatalAspectKind, int, int], ...] = (
    (NatalAspectKind.CONJUNCTION, 0_000, 8_000),
    (NatalAspectKind.SEXTILE, 60_000, 4_000),
    (NatalAspectKind.SQUARE, 90_000, 6_000),
    (NatalAspectKind.TRINE, 120_000, 6_000),
    (NatalAspectKind.OPPOSITION, 180_000, 8_000),
)
_SIGNS = tuple(ZodiacSign)
_MAX_TRANSIT_ASPECTS_PER_SAMPLE = 24


class NatalChartProvider(Protocol):
    async def calculate_for_user(self, user_id: UUID) -> NatalChartResult: ...


class HoroscopeFactService:
    """Build an immutable bounded fact bundle without exposing raw birth-profile fields."""

    def __init__(self, charts: NatalChartProvider) -> None:
        self._charts = charts

    async def calculate_for_user(
        self,
        user_id: UUID,
        scope: HoroscopeScope,
        *,
        reference_date: date | None = None,
    ) -> HoroscopeFactBundle:
        chart = await self._charts.calculate_for_user(user_id)
        return self.build(
            chart,
            scope,
            reference_date=reference_date or datetime.now(UTC).date(),
        )

    def build(
        self,
        chart: NatalChartResult,
        scope: HoroscopeScope,
        *,
        reference_date: date,
    ) -> HoroscopeFactBundle:
        period_start, period_end, sample_dates = self._period(scope, reference_date)
        facts = list(self._natal_facts(chart))
        if sample_dates:
            facts.extend(self._transit_facts(chart, sample_dates))
        limitations = [
            HoroscopeLimitation.ENTERTAINMENT_ONLY,
            HoroscopeLimitation.NO_CERTAIN_PREDICTION,
        ]
        if chart.time_precision is NatalTimePrecision.DATE_ONLY:
            limitations.append(HoroscopeLimitation.BIRTH_TIME_UNKNOWN)
        if sample_dates:
            limitations.append(HoroscopeLimitation.SAMPLED_TRANSITS)
        anchor_date = period_start or reference_date
        return HoroscopeFactBundle(
            facts_version=HOROSCOPE_FACTS_VERSION,
            scope=scope,
            calculated_at_utc=datetime.combine(anchor_date, time(12), tzinfo=UTC),
            period_start=period_start,
            period_end=period_end,
            natal_schema_version=chart.schema_version,
            natal_engine_version=chart.engine_version,
            facts=tuple(sorted(facts, key=lambda fact: fact.fact_id)),
            limitations=tuple(limitations),
        )

    @staticmethod
    def _period(
        scope: HoroscopeScope,
        reference_date: date,
    ) -> tuple[date | None, date | None, tuple[date, ...]]:
        if scope is HoroscopeScope.DAY_FORECAST:
            return reference_date, reference_date, (reference_date,)
        if scope is HoroscopeScope.WEEK_FORECAST:
            start = reference_date - timedelta(days=reference_date.weekday())
            end = start + timedelta(days=6)
            return start, end, (start, start + timedelta(days=3), end)
        if scope is HoroscopeScope.MONTH_FORECAST:
            start = reference_date.replace(day=1)
            last_day = calendar.monthrange(start.year, start.month)[1]
            end = start.replace(day=last_day)
            midpoint = start.replace(day=(last_day + 1) // 2)
            return start, end, tuple(dict.fromkeys((start, midpoint, end)))
        return None, None, ()

    @staticmethod
    def _natal_facts(chart: NatalChartResult) -> tuple[HoroscopeFact, ...]:
        facts: list[HoroscopeFact] = []
        for position in chart.planets:
            facts.append(
                HoroscopeFact(
                    fact_id=f"natal:planet:{position.body.value}",
                    kind=HoroscopeFactKind.NATAL_PLANET,
                    details=position.payload(),
                )
            )
        for aspect in chart.aspects:
            facts.append(
                HoroscopeFact(
                    fact_id=(
                        f"natal:aspect:{aspect.first_body.value}:"
                        f"{aspect.second_body.value}:{aspect.kind.value}"
                    ),
                    kind=HoroscopeFactKind.NATAL_ASPECT,
                    details=aspect.payload(),
                )
            )
        for house in chart.houses:
            facts.append(
                HoroscopeFact(
                    fact_id=f"natal:house:{house.number}",
                    kind=HoroscopeFactKind.NATAL_HOUSE,
                    details=house.payload(),
                )
            )
        if chart.ascendant_longitude_millidegrees is not None:
            longitude = chart.ascendant_longitude_millidegrees
            facts.append(
                HoroscopeFact(
                    fact_id="natal:ascendant",
                    kind=HoroscopeFactKind.NATAL_ASCENDANT,
                    details={
                        "longitude_millidegrees": longitude,
                        "sign": _SIGNS[longitude // 30_000].value,
                        "sign_degree_millidegrees": longitude % 30_000,
                        "house_system": chart.house_system,
                    },
                )
            )
        return tuple(facts)

    def _transit_facts(
        self,
        chart: NatalChartResult,
        sample_dates: tuple[date, ...],
    ) -> tuple[HoroscopeFact, ...]:
        facts: list[HoroscopeFact] = []
        natal_positions = {position.body: position for position in chart.planets}
        for sample_date in sample_dates:
            astro_time = self._astro_time(sample_date)
            transit_positions = {
                body: self._position(body, engine_body, astro_time)
                for body, engine_body in _TRANSIT_BODIES
            }
            for body, details in transit_positions.items():
                facts.append(
                    HoroscopeFact(
                        fact_id=f"transit:{sample_date.isoformat()}:planet:{body.value}",
                        kind=HoroscopeFactKind.TRANSIT_PLANET,
                        details={"sample_date": sample_date.isoformat(), **details},
                    )
                )
            sample_aspects: list[HoroscopeFact] = []
            for transit_body, transit in transit_positions.items():
                for natal_body, natal in natal_positions.items():
                    sample_aspects.extend(
                        self._cross_aspect_facts(
                            sample_date,
                            transit_body,
                            transit["longitude_millidegrees"],
                            natal_body,
                            natal.longitude_millidegrees,
                        )
                    )
            facts.extend(
                sorted(
                    sample_aspects,
                    key=lambda fact: (self._fact_orb(fact), fact.fact_id),
                )[:_MAX_TRANSIT_ASPECTS_PER_SAMPLE]
            )
        return tuple(facts)

    @staticmethod
    def _fact_orb(fact: HoroscopeFact) -> int:
        value = fact.details.get("orb_millidegrees")
        if not isinstance(value, int):
            raise TypeError("transit aspect orb must be an integer millidegree value")
        return value

    @staticmethod
    def _astro_time(sample_date: date) -> Any:
        return astronomy.Time.Make(
            sample_date.year,
            sample_date.month,
            sample_date.day,
            12,
            0,
            0.0,
        )

    def _position(self, body: NatalBody, engine_body: Any, astro_time: Any) -> dict[str, object]:
        longitude = self._longitude(engine_body, astro_time)
        before = self._longitude(engine_body, astro_time.AddDays(-0.5))
        after = self._longitude(engine_body, astro_time.AddDays(0.5))
        longitude_millidegrees = self._millidegrees(longitude)
        return {
            "body": body.value,
            "longitude_millidegrees": longitude_millidegrees,
            "sign": _SIGNS[longitude_millidegrees // 30_000].value,
            "sign_degree_millidegrees": longitude_millidegrees % 30_000,
            "retrograde": self._signed_angle(after - before) < 0.0,
        }

    @staticmethod
    def _longitude(engine_body: Any, astro_time: Any) -> float:
        vector = astronomy.GeoVector(engine_body, astro_time, True)
        return float(astronomy.Ecliptic(vector).elon) % 360.0

    @staticmethod
    def _millidegrees(value: float) -> int:
        return round((value % 360.0) * 1000.0) % 360_000

    @staticmethod
    def _signed_angle(value: float) -> float:
        return (value + 540.0) % 360.0 - 180.0

    @staticmethod
    def _cross_aspect_facts(
        sample_date: date,
        transit_body: NatalBody,
        transit_longitude: object,
        natal_body: NatalBody,
        natal_longitude: int,
    ) -> tuple[HoroscopeFact, ...]:
        if not isinstance(transit_longitude, int):
            raise TypeError("transit longitude must be an integer millidegree value")
        separation = abs(transit_longitude - natal_longitude)
        separation = min(separation, 360_000 - separation)
        kind, exact_angle, maximum_orb = min(
            _ASPECTS,
            key=lambda candidate: abs(separation - candidate[1]),
        )
        orb = abs(separation - exact_angle)
        if orb > maximum_orb:
            return ()
        return (
            HoroscopeFact(
                fact_id=(
                    f"transit:{sample_date.isoformat()}:{transit_body.value}:"
                    f"natal:{natal_body.value}:{kind.value}"
                ),
                kind=HoroscopeFactKind.TRANSIT_NATAL_ASPECT,
                details={
                    "sample_date": sample_date.isoformat(),
                    "transit_body": transit_body.value,
                    "natal_body": natal_body.value,
                    "kind": kind.value,
                    "separation_millidegrees": separation,
                    "orb_millidegrees": orb,
                },
            ),
        )
