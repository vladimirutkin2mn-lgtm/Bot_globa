"""Deterministic Horoscope fact-bundle tests."""

from datetime import date

import pytest

from app.domain.horoscope import (
    HoroscopeFact,
    HoroscopeFactKind,
    HoroscopeLimitation,
    HoroscopeScope,
)
from tests.horoscope_helpers import sample_fact_bundle


def test_same_chart_and_period_produce_identical_fact_payload_and_digest() -> None:
    first = sample_fact_bundle(
        HoroscopeScope.WEEK_FORECAST,
        reference_date=date(2026, 8, 6),
    )
    second = sample_fact_bundle(
        HoroscopeScope.WEEK_FORECAST,
        reference_date=date(2026, 8, 9),
    )

    assert first.period_start == date(2026, 8, 3)
    assert first.period_end == date(2026, 8, 9)
    assert first.payload() == second.payload()
    assert first.digest() == second.digest()
    assert HoroscopeLimitation.SAMPLED_TRANSITS in first.limitations
    assert any(fact.kind is HoroscopeFactKind.TRANSIT_PLANET for fact in first.facts)
    transit_aspects = [
        fact
        for fact in first.facts
        if fact.kind is HoroscopeFactKind.TRANSIT_NATAL_ASPECT
    ]
    assert transit_aspects
    assert len(transit_aspects) <= 3 * 24


def test_month_forecast_uses_calendar_month_and_three_fixed_samples() -> None:
    bundle = sample_fact_bundle(
        HoroscopeScope.MONTH_FORECAST,
        reference_date=date(2026, 8, 27),
    )

    assert bundle.period_start == date(2026, 8, 1)
    assert bundle.period_end == date(2026, 8, 31)
    transit_dates = {
        fact.details["sample_date"]
        for fact in bundle.facts
        if fact.kind is HoroscopeFactKind.TRANSIT_PLANET
    }
    assert transit_dates == {"2026-08-01", "2026-08-16", "2026-08-31"}


def test_unknown_birth_time_never_creates_house_or_ascendant_facts() -> None:
    bundle = sample_fact_bundle(exact_time=False)

    assert HoroscopeLimitation.BIRTH_TIME_UNKNOWN in bundle.limitations
    assert all(
        fact.kind
        not in {HoroscopeFactKind.NATAL_HOUSE, HoroscopeFactKind.NATAL_ASCENDANT}
        for fact in bundle.facts
    )


def test_non_forecast_astrology_facts_do_not_depend_on_reference_date() -> None:
    first = sample_fact_bundle(
        HoroscopeScope.NATAL_PROFILE,
        reference_date=date(2026, 1, 1),
    )
    second = sample_fact_bundle(
        HoroscopeScope.NATAL_PROFILE,
        reference_date=date(2026, 12, 31),
    )

    assert first.period_start is None and first.period_end is None
    assert first.facts == second.facts
    assert first.limitations == second.limitations
    assert first.digest() != second.digest()
    assert HoroscopeLimitation.SAMPLED_TRANSITS not in first.limitations


def test_fact_contract_rejects_raw_birth_fields_before_prompt_construction() -> None:
    details: dict[str, object] = {
        "body": "sun",
        "longitude_millidegrees": 11_000,
        "sign": "aries",
        "sign_degree_millidegrees": 11_000,
        "retrograde": False,
        "birth_date": "1991-04-17",
        "latitude": 52.367573,
    }

    with pytest.raises(ValueError, match="detail fields"):
        HoroscopeFact(
            fact_id="natal:planet:sun",
            kind=HoroscopeFactKind.NATAL_PLANET,
            details=details,
        )


def test_fact_contract_rejects_inconsistent_identity_and_angles() -> None:
    with pytest.raises(ValueError, match="does not match details"):
        HoroscopeFact(
            fact_id="natal:planet:moon",
            kind=HoroscopeFactKind.NATAL_PLANET,
            details={
                "body": "sun",
                "longitude_millidegrees": 11_000,
                "sign": "aries",
                "sign_degree_millidegrees": 11_000,
                "retrograde": False,
            },
        )

    with pytest.raises(ValueError, match="orb does not match separation"):
        HoroscopeFact(
            fact_id="natal:aspect:moon:sun:trine",
            kind=HoroscopeFactKind.NATAL_ASPECT,
            details={
                "first_body": "moon",
                "second_body": "sun",
                "kind": "trine",
                "separation_millidegrees": 120_000,
                "orb_millidegrees": 1_000,
            },
        )
