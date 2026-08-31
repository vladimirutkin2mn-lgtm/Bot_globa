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
    assert first.methodology_version == DAILY_SOLAR_METHOD_VERSION == "solar-sign-daily-v3"
    assert tuple(item.sign for item in first.signs) == tuple(ZodiacSign)
    assert DailyHoroscopeSnapshot.from_payload(first.payload()) == first


def test_editorial_daily_v5_is_unique_human_and_caption_safe() -> None:
    snapshot = build_editorial_daily_horoscope(date(2026, 8, 16))
    rendered = render_daily_horoscope(snapshot)
    texts = [item.text for item in snapshot.signs]

    assert snapshot.methodology_version == DAILY_EDITORIAL_METHOD_VERSION == "solar-sign-daily-v5"
    assert tuple(item.sign for item in snapshot.signs) == tuple(ZodiacSign)
    assert len(set(texts)) == len(ZodiacSign)
    assert all(": " not in text for text in texts)
    assert all(";" not in text for text in texts)
    assert "чувства подскажут верный темп" not in rendered
    assert "неожиданный поворот может помочь" not in rendered
    assert len(rendered) <= TELEGRAM_CAPTION_LIMIT


def test_editorial_daily_v5_is_deterministic_and_roundtrippable() -> None:
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


def test_daily_v5_changes_shared_theme_on_adjacent_days() -> None:
    first = build_daily_horoscope(date(2026, 8, 30))
    second = build_daily_horoscope(date(2026, 8, 31))

    assert first.theme != second.theme


def test_daily_v5_fourteen_day_audit_never_repeats_identical_sign_copy() -> None:
    snapshots = [
        build_editorial_daily_horoscope(date.fromordinal(date(2026, 8, 18).toordinal() + offset))
        for offset in range(14)
    ]

    assert all(
        snapshots[index - 1].theme != snapshots[index].theme
        for index in range(1, len(snapshots))
    )

    for sign_index, _sign in enumerate(ZodiacSign):
        texts = [snapshot.signs[sign_index].text for snapshot in snapshots]
        assert all(previous != current for previous, current in zip(texts, texts[1:]))
        assert len(set(texts)) >= 4


def test_daily_v5_fourteen_day_audit_limits_topic_streaks() -> None:
    snapshots = [
        build_daily_horoscope(date.fromordinal(date(2026, 8, 18).toordinal() + offset))
        for offset in range(14)
    ]

    for sign_index, _sign in enumerate(ZodiacSign):
        topics = [snapshot.signs[sign_index].text.partition(": ")[0] for snapshot in snapshots]
        longest = 1
        current = 1
        for previous, topic in zip(topics, topics[1:]):
            current = current + 1 if previous == topic else 1
            longest = max(longest, current)
        assert longest <= 2
