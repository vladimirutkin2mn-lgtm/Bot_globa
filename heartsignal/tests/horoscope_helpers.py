"""Shared deterministic fixtures for Horoscope unit and integration tests."""

from datetime import UTC, date, datetime
from uuid import UUID

from app.domain.horoscope import HoroscopeFactBundle, HoroscopeScope
from app.domain.natal_chart import (
    NATAL_CHART_ENGINE_VERSION,
    NATAL_CHART_HOUSE_SYSTEM,
    NATAL_CHART_SCHEMA_VERSION,
    NatalBody,
    NatalChartResult,
    NatalHouse,
    NatalPlanetPosition,
    NatalTimePrecision,
    ZodiacSign,
)
from app.services.horoscope_facts import HoroscopeFactService

_SIGNS = tuple(ZodiacSign)


class UnusedNatalChartProvider:
    async def calculate_for_user(self, user_id: UUID) -> NatalChartResult:
        raise AssertionError(f"unexpected chart lookup for {user_id}")


def sample_natal_chart(*, exact_time: bool = True) -> NatalChartResult:
    positions = tuple(
        NatalPlanetPosition(
            body=body,
            longitude_millidegrees=(11_000 + index * 31_000) % 360_000,
            sign=_SIGNS[((11_000 + index * 31_000) % 360_000) // 30_000],
            sign_degree_millidegrees=(11_000 + index * 31_000) % 30_000,
            retrograde=index in {2, 6, 8},
        )
        for index, body in enumerate(NatalBody)
    )
    ascendant = 17_000 if exact_time else None
    houses = (
        tuple(
            NatalHouse(
                number=number,
                cusp_longitude_millidegrees=(17_000 + (number - 1) * 30_000) % 360_000,
                sign=_SIGNS[((17_000 + (number - 1) * 30_000) % 360_000) // 30_000],
            )
            for number in range(1, 13)
        )
        if exact_time
        else ()
    )
    return NatalChartResult(
        schema_version=NATAL_CHART_SCHEMA_VERSION,
        engine_version=NATAL_CHART_ENGINE_VERSION,
        normalization_version="birth-profile-normalizer-v1",
        time_precision=(NatalTimePrecision.EXACT if exact_time else NatalTimePrecision.DATE_ONLY),
        calculation_utc=datetime(1991, 4, 17, 6, 35, tzinfo=UTC),
        calculation_assumption=None if exact_time else "local_noon",
        planets=positions,
        aspects=(),
        houses=houses,
        ascendant_longitude_millidegrees=ascendant,
        house_system=NATAL_CHART_HOUSE_SYSTEM if exact_time else None,
    )


def sample_fact_bundle(
    scope: HoroscopeScope = HoroscopeScope.NATAL_PROFILE,
    *,
    exact_time: bool = True,
    reference_date: date = date(2026, 8, 6),
) -> HoroscopeFactBundle:
    return HoroscopeFactService(UnusedNatalChartProvider()).build(
        sample_natal_chart(exact_time=exact_time),
        scope,
        reference_date=reference_date,
    )


def valid_horoscope_payload(bundle: HoroscopeFactBundle) -> dict[str, object]:
    primary_fact = bundle.facts[0].fact_id
    return {
        "title": "A reflective profile",
        "scope": bundle.scope.value,
        "facts_digest": bundle.digest(),
        "overview": "Several calculated patterns may support slower observation before action.",
        "interpretations": [
            {
                "fact_ids": [primary_fact],
                "text": (
                    "This pattern may be useful as a prompt to balance initiative with patience."
                ),
            }
        ],
        "themes": ["Measured pacing may make the next choice easier to evaluate."],
        "possible_scenarios": [
            {
                "scenario": "A reversible experiment may reveal which direction feels sustainable.",
                "conditions": ["Keep the first step small and observe the response."],
            }
        ],
        "reflection_questions": ["What evidence would make the next step feel proportionate?"],
        "practical_step": "Write down one reversible action and one boundary before deciding.",
        "limitations": [value.value for value in bundle.limitations],
        "uncertainty_note": "This interpretation cannot predict events or replace your judgment.",
        "share_card": {
            "headline": "A reflective pattern",
            "short_text": "Pause, observe, and choose one reversible next step.",
        },
        "safety": {"high_risk_detected": False, "categories": []},
    }
