from datetime import date

from app.bot.daily_horoscope import render_daily_horoscope
from app.bot.scene_media import TELEGRAM_CAPTION_LIMIT
from app.domain.horoscope import HoroscopeScope
from app.domain.horoscope_topic import HoroscopeTopic
from app.domain.natal_chart import NatalBody, ZodiacSign
from app.services.daily_sky import (
    DailyHoroscopeSnapshot,
    build_daily_horoscope,
    calculate_daily_sky,
)


def test_daily_sky_contains_every_supported_planet_once() -> None:
    sky = calculate_daily_sky(date(2026, 8, 16))

    assert tuple(planet.body for planet in sky.planets) == tuple(NatalBody)
    assert len({planet.body for planet in sky.planets}) == len(NatalBody)
    assert sky.forecast_date == date(2026, 8, 16)
    assert len(sky.digest()) == 64


def test_solar_daily_snapshot_is_deterministic_complete_and_roundtrippable() -> None:
    first = build_daily_horoscope(date(2026, 8, 16))
    second = build_daily_horoscope(date(2026, 8, 16))

    assert first == second
    assert tuple(item.sign for item in first.signs) == tuple(ZodiacSign)
    assert DailyHoroscopeSnapshot.from_payload(first.payload()) == first
    assert len(render_daily_horoscope(first)) <= TELEGRAM_CAPTION_LIMIT


def test_personal_daily_topic_freezes_one_date() -> None:
    topic = HoroscopeTopic.for_request(
        HoroscopeScope.DAY_FORECAST,
        date(2026, 8, 16),
    )

    assert topic.storage_value() == "day_forecast__2026_08_16"
    assert HoroscopeTopic.parse(topic.storage_value()) == topic
