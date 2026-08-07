"""Deterministic fixtures for the versioned Astronomy Engine natal chart."""

from datetime import date, time

from app.domain.birth_profile import BirthProfileInput
from app.domain.natal_chart import (
    NATAL_CHART_ENGINE_VERSION,
    NATAL_CHART_HOUSE_SYSTEM,
    NATAL_CHART_SCHEMA_VERSION,
    NatalBody,
    NatalTimePrecision,
    ZodiacSign,
)
from app.services.natal_chart import AstronomyEngineNatalChartCalculator


def _exact_profile() -> BirthProfileInput:
    return BirthProfileInput(
        birth_date=date(1991, 4, 17),
        birth_time=time(8, 35),
        birth_place="Amsterdam",
        timezone="Europe/Amsterdam",
        latitude=52.367573,
        longitude=4.904139,
        utc_offset_minutes=120,
    )


def _date_only_profile() -> BirthProfileInput:
    return BirthProfileInput(
        birth_date=date(1991, 4, 17),
        birth_time=None,
        birth_place="Amsterdam",
        timezone="Europe/Amsterdam",
        latitude=52.367573,
        longitude=4.904139,
        utc_offset_minutes=120,
    )


def test_same_normalized_input_produces_identical_versioned_payload() -> None:
    calculator = AstronomyEngineNatalChartCalculator()

    first = calculator.calculate(_exact_profile())
    second = calculator.calculate(_exact_profile())

    assert first == second
    assert first.payload() == second.payload()
    assert first.schema_version == NATAL_CHART_SCHEMA_VERSION
    assert first.engine_version == NATAL_CHART_ENGINE_VERSION
    assert first.calculation_utc.isoformat() == "1991-04-17T06:35:00+00:00"
    assert tuple(position.body for position in first.planets) == tuple(NatalBody)
    assert len(first.planets) == 10
    assert len({position.longitude_millidegrees for position in first.planets}) == 10
    sun = next(position for position in first.planets if position.body is NatalBody.SUN)
    assert sun.sign is ZodiacSign.ARIES
    assert 20_000 <= sun.sign_degree_millidegrees < 30_000


def test_exact_time_produces_ascendant_and_twelve_equal_houses() -> None:
    result = AstronomyEngineNatalChartCalculator().calculate(_exact_profile())

    assert result.time_precision is NatalTimePrecision.EXACT
    assert result.calculation_assumption is None
    assert result.house_system == NATAL_CHART_HOUSE_SYSTEM
    assert result.ascendant_longitude_millidegrees is not None
    assert len(result.houses) == 12
    assert result.houses[0].number == 1
    assert result.houses[0].cusp_longitude_millidegrees == result.ascendant_longitude_millidegrees
    for previous, current in zip(result.houses, result.houses[1:]):
        assert (
            current.cusp_longitude_millidegrees - previous.cusp_longitude_millidegrees
        ) % 360_000 == 30_000
    assert (
        result.houses[6].cusp_longitude_millidegrees - result.houses[0].cusp_longitude_millidegrees
    ) % 360_000 == 180_000


def test_unknown_time_uses_local_noon_and_never_invents_houses() -> None:
    result = AstronomyEngineNatalChartCalculator().calculate(_date_only_profile())

    assert result.time_precision is NatalTimePrecision.DATE_ONLY
    assert result.calculation_assumption == "local_noon"
    assert result.calculation_utc.isoformat() == "1991-04-17T10:00:00+00:00"
    assert result.ascendant_longitude_millidegrees is None
    assert result.house_system is None
    assert result.houses == ()
    assert len(result.planets) == 10


def test_aspects_are_stably_ordered_and_within_declared_orbs() -> None:
    result = AstronomyEngineNatalChartCalculator().calculate(_exact_profile())
    ordering = [
        (aspect.first_body.value, aspect.second_body.value, aspect.kind.value)
        for aspect in result.aspects
    ]

    assert ordering == sorted(ordering)
    for aspect in result.aspects:
        assert aspect.first_body.value < aspect.second_body.value
        assert 0 <= aspect.orb_millidegrees <= 8_000
        assert 0 <= aspect.separation_millidegrees <= 180_000


def test_location_changes_houses_but_not_geocentric_planets_at_same_instant() -> None:
    calculator = AstronomyEngineNatalChartCalculator()
    amsterdam = _exact_profile()
    paris = BirthProfileInput(
        birth_date=amsterdam.birth_date,
        birth_time=amsterdam.birth_time,
        birth_place="Paris",
        timezone="Europe/Paris",
        latitude=48.8566,
        longitude=2.3522,
        utc_offset_minutes=120,
    )

    first = calculator.calculate(amsterdam)
    second = calculator.calculate(paris)

    assert first.calculation_utc == second.calculation_utc
    assert first.planets == second.planets
    assert first.aspects == second.aspects
    assert first.ascendant_longitude_millidegrees != second.ascendant_longitude_millidegrees
