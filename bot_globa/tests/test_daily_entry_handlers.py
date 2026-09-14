"""Contracts for the first on-demand daily horoscope entry."""

from aiogram.types import InlineKeyboardMarkup

from app.bot import chat_scope_handlers
from app.bot.daily_entry_handlers import needs_daily_sign
from app.bot.daily_entry_handlers import router as daily_entry_router
from app.bot.daily_keyboards import (
    DAILY_PERSONAL_CALLBACK,
    DAILY_SHARE_CALLBACK,
    daily_horoscope_with_sign_keyboard,
    daily_more_keyboard,
    daily_sign_keyboard,
)
from app.domain.daily_horoscope import DailyHoroscopeMode, DailyHoroscopePreferenceView
from app.domain.natal_chart import ZodiacSign


def _preference(sign: ZodiacSign | None) -> DailyHoroscopePreferenceView:
    return DailyHoroscopePreferenceView(
        mode=DailyHoroscopeMode.MORNING,
        timezone="Europe/Moscow",
        next_delivery_at=None,
        zodiac_sign=sign,
    )


def _callbacks(markup: InlineKeyboardMarkup) -> set[str]:
    return {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    }


def test_first_daily_entry_requires_sign_only_until_one_is_saved() -> None:
    assert needs_daily_sign(_preference(None)) is True
    assert needs_daily_sign(_preference(next(iter(ZodiacSign)))) is False


def test_first_sign_picker_has_explicit_all_signs_alternative() -> None:
    callbacks = _callbacks(daily_sign_keyboard(None))
    assert "daily:all" in callbacks
    assert "daily:sign:clear" not in callbacks


def test_daily_forecast_keeps_only_primary_actions_visible() -> None:
    callbacks = _callbacks(daily_horoscope_with_sign_keyboard(next(iter(ZodiacSign))))
    assert callbacks == {
        DAILY_PERSONAL_CALLBACK,
        DAILY_SHARE_CALLBACK,
        "daily:more",
        "menu:home",
    }


def test_daily_more_screen_keeps_secondary_actions_available() -> None:
    callbacks = _callbacks(daily_more_keyboard(next(iter(ZodiacSign))))
    assert callbacks == {
        "daily:sign",
        "daily:all",
        "tarot:topic:general_forecast",
        "daily:settings",
        "menu:daily",
    }


def test_daily_entry_router_runs_before_other_private_child_routes() -> None:
    assert chat_scope_handlers.router.sub_routers[0] is daily_entry_router
