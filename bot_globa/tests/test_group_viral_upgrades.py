from datetime import date, time

from aiogram.types import InlineKeyboardMarkup

from app.bot import group_handlers, group_viral_handlers
from app.bot.group_viral_upgrades import (
    _DUEL_ROUNDS,
    _zodiac_keyboard,
    astro_duel_entry,
    duel_round_energy_for_chart,
    duel_round_energy_for_sign,
    duel_winners_for_signs,
    quick_sign_compatibility,
    viral_upgrade_action,
)
from app.domain.birth_profile import BirthProfileInput
from app.domain.natal_chart import NatalChartResult, ZodiacSign
from app.services.natal_chart import AstronomyEngineNatalChartCalculator


def _callbacks(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def _chart(day: date, hour: int) -> NatalChartResult:
    profile = BirthProfileInput(
        birth_date=day,
        birth_time=time(hour, 0),
        birth_place="Greenwich",
        timezone="UTC",
        latitude=51.4769,
        longitude=0.0,
        utc_offset_minutes=0,
    )
    return AstronomyEngineNatalChartCalculator().calculate(profile)


def test_quick_sign_compatibility_is_symmetric_and_clearly_bounded() -> None:
    first = quick_sign_compatibility(ZodiacSign.ARIES, ZodiacSign.LEO)
    second = quick_sign_compatibility(ZodiacSign.LEO, ZodiacSign.ARIES)

    assert first == second
    assert 50 <= first[0] <= 92
    assert first[1].strip()


def test_zodiac_picker_has_all_signs_and_stays_within_callback_limit() -> None:
    max_user_id = 2**52 - 1
    keyboard = _zodiac_keyboard(
        "d",
        max_user_id,
        max_user_id - 1,
        max_user_id,
        None,
        ZodiacSign.SCORPIO,
    )
    callbacks = _callbacks(keyboard)

    assert len(callbacks) == 12
    assert all(len(value.encode()) <= 64 for value in callbacks)


def test_duel_round_chart_energy_is_deterministic_and_bounded() -> None:
    chart = _chart(date(1991, 4, 8), 10)
    day = date(2026, 8, 18)

    for config in _DUEL_ROUNDS:
        first = duel_round_energy_for_chart(chart, day, config.code)
        second = duel_round_energy_for_chart(chart, day, config.code)
        assert first == second
        assert 35 <= first.score <= 95
        assert first.reason.strip()


def test_quick_duel_round_energy_is_deterministic_and_bounded() -> None:
    day = date(2026, 8, 18)

    for config in _DUEL_ROUNDS:
        first = duel_round_energy_for_sign(ZodiacSign.AQUARIUS, day, config.code)
        second = duel_round_energy_for_sign(ZodiacSign.AQUARIUS, day, config.code)
        assert first == second
        assert 35 <= first.score <= 95
        assert first.reason.strip()


def test_three_round_sign_duel_always_has_an_overall_winner() -> None:
    winners = duel_winners_for_signs(
        101,
        202,
        ZodiacSign.GEMINI,
        ZodiacSign.CAPRICORN,
        date(2026, 8, 18),
    )

    assert len(winners) == 3
    assert set(winners) <= {101, 202}
    assert winners.count(101) != winners.count(202)
    assert max(winners.count(101), winners.count(202)) >= 2


def test_upgrade_replaces_one_shot_duel_and_registers_callback_flow() -> None:
    message_callbacks = [handler.callback for handler in group_handlers.router.message.handlers]
    callback_callbacks = [
        handler.callback for handler in group_handlers.router.callback_query.handlers
    ]

    assert group_viral_handlers.astro_duel_entry not in message_callbacks
    assert astro_duel_entry in message_callbacks
    assert viral_upgrade_action in callback_callbacks
