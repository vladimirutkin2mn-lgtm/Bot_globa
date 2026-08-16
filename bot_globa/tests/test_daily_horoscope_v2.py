from datetime import date

from app.bot.daily_horoscope import render_daily_horoscope
from app.bot.scene_media import TELEGRAM_CAPTION_LIMIT
from app.domain.horoscope import HoroscopeScope
from app.domain.horoscope_topic import HoroscopeTopic
from app.domain.natal_chart import NatalBody, ZodiacSign
from app.services.daily_horoscope_editorial import (
    DAILY_EDITORIAL_METHOD_VERSION,
    build_editorial_daily_horoscope,
)
from app.services.daily_sky import (
    DAILY_SOLAR_METHOD_VERSION,
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
    assert first.methodology_version == DAILY_SOLAR_METHOD_VERSION == "solar-sign-daily-v2"
    assert tuple(item.sign for item in first.signs) == tuple(ZodiacSign)
    assert DailyHoroscopeSnapshot.from_payload(first.payload()) == first


def test_editorial_daily_v3_is_unique_human_and_caption_safe() -> None:
    snapshot = build_editorial_daily_horoscope(date(2026, 8, 16))
    rendered = render_daily_horoscope(snapshot)
    texts = [item.text for item in snapshot.signs]

    assert snapshot.methodology_version == DAILY_EDITORIAL_METHOD_VERSION == "solar-sign-daily-v3"
    assert tuple(item.sign for item in snapshot.signs) == tuple(ZodiacSign)
    assert len(set(texts)) == len(ZodiacSign)
    assert all(": " not in text for text in texts)
    assert "чувства подскажут верный темп" not in rendered
    assert "неожиданный поворот может помочь" not in rendered
    assert len(rendered) <= TELEGRAM_CAPTION_LIMIT


def test_editorial_daily_v3_is_deterministic_and_roundtrippable() -> None:
    first = build_editorial_daily_horoscope(date(2026, 8, 16))
    second = build_editorial_daily_horoscope(date(2026, 8, 16))

    assert first == second
    assert DailyHoroscopeSnapshot.from_payload(first.payload()) == first
    assert render_daily_horoscope(date(2026, 8, 16)) == render_daily_horoscope(first)


def test_personal_daily_topic_freezes_one_date() -> None:
    topic = HoroscopeTopic.for_request(
        HoroscopeScope.DAY_FORECAST,
        date(2026, 8, 16),
    )

    assert topic.storage_value() == "day_forecast__2026_08_16"
    assert HoroscopeTopic.parse(topic.storage_value()) == topic
