from datetime import date, time

from aiogram.types import InlineKeyboardMarkup

from app.bot import group_handlers, group_social_handlers, group_viral_handlers
from app.bot.group_viral_handlers import (
    _couple_keyboard,
    _decode_users,
    _encode_users,
    _seance_keyboard,
    cosmic_advice_for_day,
    cosmic_energy_for_day,
    couple_pair_for_day,
    group_advice,
    group_couple,
    group_seance,
    group_taro_yes_no,
    tarot_yes_no_for_question,
    viral_action,
)
from app.bot.group_viral_upgrades import astro_duel_entry
from app.domain.birth_profile import BirthProfileInput
from app.domain.natal_chart import NatalChartResult
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


def test_opt_in_user_encoding_round_trips_and_fits_callback_limit() -> None:
    users = tuple((2**52 - 1) - index for index in range(5))
    payload = _encode_users(users)

    assert _decode_users(payload) == tuple(sorted(users))
    assert all(len(value.encode()) <= 64 for value in _callbacks(_couple_keyboard(users)))
    assert all(len(value.encode()) <= 64 for value in _callbacks(_seance_keyboard(users[:2])))


def test_couple_pair_is_stable_and_independent_of_join_order() -> None:
    day = date(2026, 8, 17)
    users = (101, 202, 303, 404, 505)

    first = couple_pair_for_day(-1001234567890, users, day)
    second = couple_pair_for_day(-1001234567890, tuple(reversed(users)), day)

    assert first == second
    assert len(set(first)) == 2
    assert set(first) <= set(users)


def test_tarot_yes_no_is_stable_for_same_question() -> None:
    day = date(2026, 8, 17)

    first = tarot_yes_no_for_question(-1001, 42, "Ехать сегодня?", day)
    second = tarot_yes_no_for_question(-1001, 42, "  ехать   сегодня? ", day)

    assert first == second
    assert first.answer in {"ДА", "НЕТ"}
    assert first.reason.strip()


def test_cosmic_energy_uses_real_transits_and_stays_bounded() -> None:
    chart = _chart(date(1991, 4, 8), 10)
    day = date(2026, 8, 17)

    first = cosmic_energy_for_day(chart, day)
    second = cosmic_energy_for_day(chart, day)

    assert first == second
    assert 35 <= first.score <= 95
    assert first.reason.strip()


def test_cosmic_advice_is_deterministic_and_exposes_planet_context() -> None:
    day = date(2026, 8, 17)

    first = cosmic_advice_for_day(day)
    second = cosmic_advice_for_day(day)

    assert first == second
    assert first.mercury_sign.strip()
    assert first.moon_sign.strip()
    assert first.text.strip()


def test_new_group_handlers_replace_reply_duel_and_register_collective_games() -> None:
    message_callbacks = [handler.callback for handler in group_handlers.router.message.handlers]
    callback_callbacks = [
        handler.callback for handler in group_handlers.router.callback_query.handlers
    ]

    assert group_social_handlers.group_duel not in message_callbacks
    assert group_viral_handlers.astro_duel_entry not in message_callbacks
    assert astro_duel_entry in message_callbacks
    assert group_couple in message_callbacks
    assert group_seance in message_callbacks
    assert group_taro_yes_no in message_callbacks
    assert group_advice in message_callbacks
    assert message_callbacks.count(group_handlers.group_card) >= 2
    assert viral_action in callback_callbacks
