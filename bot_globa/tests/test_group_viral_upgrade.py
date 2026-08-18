from datetime import date, time

from app.bot.group_viral_upgrade import (
    _fallback_keyboard,
    _sign_keyboard,
    duel_series_for_charts,
    duel_series_for_signs,
    quick_compatibility_for_signs,
)
from app.domain.birth_profile import BirthProfileInput
from app.domain.natal_chart import NatalChartResult, ZodiacSign
from app.services.natal_chart import AstronomyEngineNatalChartCalculator


def _chart(day: date, hour: int) -> NatalChartResult:
    return AstronomyEngineNatalChartCalculator().calculate(
        BirthProfileInput(
            birth_date=day,
            birth_time=time(hour, 0),
            birth_place="Greenwich",
            timezone="UTC",
            latitude=51.4769,
            longitude=0.0,
            utc_offset_minutes=0,
        )
    )


def _callback_data(keyboard: object) -> list[str]:
    rows = getattr(keyboard, "inline_keyboard")
    return [button.callback_data for row in rows for button in row if button.callback_data is not None]


def test_quick_sign_compatibility_is_stable_and_bounded() -> None:
    first = quick_compatibility_for_signs(ZodiacSign.ARIES, ZodiacSign.LIBRA)
    second = quick_compatibility_for_signs(ZodiacSign.ARIES, ZodiacSign.LIBRA)

    assert first == second
    assert all(
        35 <= score <= 95
        for score in (
            first.overall,
            first.attraction,
            first.communication,
            first.long_term,
        )
    )


def test_chart_duel_has_three_distinct_rounds_and_one_winner() -> None:
    first = _chart(date(1991, 4, 8), 10)
    second = _chart(date(1994, 11, 21), 18)

    result = duel_series_for_charts(first, second, 101, 202, date(2026, 8, 18))

    assert [round_.title for round_ in result.rounds] == [
        "🔥 Марс — напор",
        "🌙 Луна — интуиция",
        "✨ Венера — обаяние",
    ]
    assert result.first_wins + result.second_wins == 3
    assert result.winner_id in {101, 202}
    assert all(round_.winner_id in {101, 202} for round_ in result.rounds)


def test_sign_duel_is_deterministic_and_plays_all_rounds() -> None:
    day = date(2026, 8, 18)
    first = duel_series_for_signs(
        ZodiacSign.SCORPIO,
        ZodiacSign.GEMINI,
        101,
        202,
        day,
    )
    second = duel_series_for_signs(
        ZodiacSign.SCORPIO,
        ZodiacSign.GEMINI,
        101,
        202,
        day,
    )

    assert first == second
    assert first.first_wins + first.second_wins == 3


def test_fallback_and_sign_picker_callbacks_fit_telegram_limit() -> None:
    fallback = _fallback_keyboard(
        "numa_bot",
        mode="d",
        first_id=2**52 - 1,
        second_id=2**52 - 2,
        first_name="First",
        second_name="Second",
        first_chart=None,
        second_chart=None,
    )
    picker = _sign_keyboard(
        "d",
        2**52 - 1,
        2**52 - 2,
        ("x", "x"),
        0,
    )

    callbacks = _callback_data(fallback) + _callback_data(picker)
    assert callbacks
    assert all(len(value.encode()) <= 64 for value in callbacks)
