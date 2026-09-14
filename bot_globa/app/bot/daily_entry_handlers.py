"""Private-chat entry point for the daily horoscope surface.

The scheduled digest and an on-demand forecast are the same text product. The only
extra first-run step is choosing a solar sign; collecting a natal profile belongs to
the separate astrology flow.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.daily_horoscope import render_compact_daily_horoscope
from app.bot.daily_keyboards import (
    daily_horoscope_with_sign_keyboard,
    daily_more_keyboard,
    daily_sign_keyboard,
)
from app.bot.scene_media import Scene
from app.bot.screen import send_artifact, show_screen
from app.bot.states import DailyHoroscopeStates
from app.domain.daily_horoscope import DailyHoroscopePreferenceView
from app.services.daily_horoscope import DailyHoroscopePreferenceService
from app.services.onboarding import OnboardingService

router = Router(name="daily_entry")

_DAILY_SIGN_PROMPT = (
    "Какой у вас знак?\n\n"
    "Выберу ваш прогноз на сегодня. Дата, место и время рождения здесь не нужны."
)


def needs_daily_sign(preference: DailyHoroscopePreferenceView) -> bool:
    """A common daily forecast needs only a solar sign, not a natal profile."""

    return preference.zodiac_sign is None


async def _leave_timezone_input(state: FSMContext) -> None:
    if await state.get_state() == DailyHoroscopeStates.waiting_for_timezone_difference.state:
        await state.set_state(None)


@router.callback_query(F.data == "menu:daily")
async def daily_horoscope_entry(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    daily_horoscopes: DailyHoroscopePreferenceService,
) -> None:
    """Open a compact forecast, asking for the solar sign only on first entry."""

    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await _leave_timezone_input(state)

    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await callback.message.answer("Сначала отправьте /start.")
        return

    preference = await daily_horoscopes.current(user.id)
    zodiac_sign = preference.zodiac_sign
    if zodiac_sign is None:
        await show_screen(
            callback.message,
            Scene.DAILY_ZODIAC,
            _DAILY_SIGN_PROMPT,
            reply_markup=daily_sign_keyboard(None),
            state=state,
        )
        return

    today = datetime.now(ZoneInfo(preference.timezone)).date()
    await send_artifact(
        callback.message,
        Scene.DAILY_HOROSCOPE,
        render_compact_daily_horoscope(today, zodiac_sign),
        reply_markup=daily_horoscope_with_sign_keyboard(zodiac_sign),
        state=state,
    )


@router.callback_query(F.data == "daily:more")
async def daily_horoscope_more(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    daily_horoscopes: DailyHoroscopePreferenceService,
) -> None:
    """Keep sign, settings and extra practices on a secondary daily screen."""

    await callback.answer()
    if not isinstance(callback.message, Message):
        return

    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await callback.message.answer("Сначала отправьте /start.")
        return
    preference = await daily_horoscopes.current(user.id)
    await show_screen(
        callback.message,
        Scene.DAILY_SETTINGS,
        "Ещё на сегодня",
        reply_markup=daily_more_keyboard(preference.zodiac_sign),
        state=state,
    )
