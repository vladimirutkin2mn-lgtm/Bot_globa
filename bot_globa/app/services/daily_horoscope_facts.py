"""Structured application-owned facts for the mass Daily LLM narrator.

This adapter intentionally reuses the deterministic driver selection from ``daily_sky``.
The calculation layer decides every astronomical fact and the product topic; the LLM only
turns this bounded bundle into human-facing copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.natal_chart import ZodiacSign
from app.services import daily_sky


@dataclass(frozen=True, slots=True)
class DailyAspectFact:
    kind: str
    other_body: str
    orb_millidegrees: int

    def payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "other_body": self.other_body,
            "orb_millidegrees": self.orb_millidegrees,
        }


@dataclass(frozen=True, slots=True)
class DailySignFact:
    sign: ZodiacSign
    topic: str
    solar_house: int
    transit_body: str
    transit_sign: str
    retrograde: bool
    aspect: DailyAspectFact | None

    def payload(self) -> dict[str, object]:
        return {
            "sign": self.sign.value,
            "topic": self.topic,
            "solar_house": self.solar_house,
            "transit_body": self.transit_body,
            "transit_sign": self.transit_sign,
            "retrograde": self.retrograde,
            "aspect": self.aspect.payload() if self.aspect is not None else None,
        }


@dataclass(frozen=True, slots=True)
class DailyHoroscopeFactBundle:
    forecast_date: date
    sky_digest: str
    day_driver: dict[str, object] | None
    signs: tuple[DailySignFact, ...]

    def payload(self) -> dict[str, object]:
        return {
            "forecast_date": self.forecast_date.isoformat(),
            "sky_digest": self.sky_digest,
            "day_driver": self.day_driver,
            "canonical_order": [sign.value for sign in ZodiacSign],
            "signs": [item.payload() for item in self.signs],
        }


def build_daily_horoscope_facts(forecast_date: date) -> DailyHoroscopeFactBundle:
    """Return one text-free fact bundle using the existing deterministic driver selection."""

    sky = daily_sky.calculate_daily_sky(forecast_date)
    previous_sky = daily_sky.calculate_daily_sky(forecast_date - timedelta(days=1))
    day_driver = daily_sky._driver_aspect(sky)
    day_payload: dict[str, object] | None = None
    if day_driver is not None:
        day_payload = {
            "kind": day_driver.kind.value,
            "first_body": day_driver.first_body.value,
            "second_body": day_driver.second_body.value,
            "orb_millidegrees": day_driver.orb_millidegrees,
        }

    sign_facts: list[DailySignFact] = []
    for sign in ZodiacSign:
        planet, aspect = daily_sky._sign_driver(sky, sign, previous_sky=previous_sky)
        house = daily_sky._solar_house(sign, planet.sign)
        aspect_fact: DailyAspectFact | None = None
        if aspect is not None:
            other_body = (
                aspect.second_body if aspect.first_body is planet.body else aspect.first_body
            )
            aspect_fact = DailyAspectFact(
                kind=aspect.kind.value,
                other_body=other_body.value,
                orb_millidegrees=aspect.orb_millidegrees,
            )
        sign_facts.append(
            DailySignFact(
                sign=sign,
                topic=daily_sky._HOUSE_FOCUS[house],
                solar_house=house,
                transit_body=planet.body.value,
                transit_sign=planet.sign.value,
                retrograde=planet.retrograde,
                aspect=aspect_fact,
            )
        )
    return DailyHoroscopeFactBundle(
        forecast_date=forecast_date,
        sky_digest=sky.digest(),
        day_driver=day_payload,
        signs=tuple(sign_facts),
    )
