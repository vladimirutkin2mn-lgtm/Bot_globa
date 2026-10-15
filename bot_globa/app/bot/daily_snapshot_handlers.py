"""On-demand Daily screens backed by the same shared snapshot as scheduled delivery."""

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.daily_horoscope import render_compact_daily_horoscope, render_daily_horoscope
from app.bot.daily_keyboards import daily_horoscope_with_sign_keyboard
from app.bot.scene_media import Scene
from app.bot.screen import send_artifact
from app.bot.states import DailyHoroscopeStates
from app.domain.daily_horoscope import (
    DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
    DailyHoroscopeMode,
    DailyHoroscopePreferenceView,
)
from app.domain.natal_chart import ZodiacSign
from app.services.daily_horoscope import DailyHoroscopePreferenceService
from app.services.daily_horoscope_snapshot import DailyHoroscopeSnapshotService
from app.services.onboarding import OnboardingService

router = Router(name="daily-snapshot")


async def _leave_timezone_input(state: FSMContext) -> None:
    if await state.get_state() == DailyHoroscopeStates.waiting_for_timezone_difference.state:
        await state.set_state(None)


async def _preference(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    daily_horoscopes: DailyHoroscopePreferenceService,
) -> DailyHoroscopePreferenceView:
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        return DailyHoroscopePreferenceView(
            DailyHoroscopeMode.MORNING,
            DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
            None,
        )
    return await daily_horoscopes.current(user.id)


async def _show(
    message: Message,
    state: FSMContext,
    preference: DailyHoroscopePreferenceView,
    snapshots: DailyHoroscopeSnapshotService,
    *,
    all_signs: bool = False,
) -> None:
    today = datetime.now(ZoneInfo(preference.timezone)).date()
    snapshot = await snapshots.get_or_create(today)
    text = (
        render_daily_horoscope(snapshot)
        if all_signs or preference.zodiac_sign is None
        else render_compact_daily_horoscope(snapshot, preference.zodiac_sign)
    )
    await send_artifact(
        message,
        Scene.DAILY_HOROSCOPE,
        text,
        reply_markup=daily_horoscope_with_sign_keyboard(preference.zodiac_sign),
        state=state,
    )


@router.callback_query(F.data == "menu:daily")
async def daily_from_shared_snapshot(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    daily_horoscopes: DailyHoroscopePreferenceService,
    daily_snapshots: DailyHoroscopeSnapshotService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await _leave_timezone_input(state)
    preference = await _preference(callback, onboarding, daily_horoscopes)
    await _show(callback.message, state, preference, daily_snapshots)


@router.callback_query(F.data == "daily:all")
async def all_signs_from_shared_snapshot(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    daily_horoscopes: DailyHoroscopePreferenceService,
    daily_snapshots: DailyHoroscopeSnapshotService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await _leave_timezone_input(state)
    preference = await _preference(callback, onboarding, daily_horoscopes)
    await _show(callback.message, state, preference, daily_snapshots, all_signs=True)


@router.callback_query(F.data.startswith("daily:sign:"))
async def selected_sign_from_shared_snapshot(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    daily_horoscopes: DailyHoroscopePreferenceService,
    daily_snapshots: DailyHoroscopeSnapshotService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await callback.message.answer("Сначала отправьте /start.")
        return
    raw_sign = (callback.data or "").removeprefix("daily:sign:")
    try:
        zodiac_sign = None if raw_sign == "clear" else ZodiacSign(raw_sign)
        preference = await daily_horoscopes.set_zodiac_sign(user.id, zodiac_sign)
    except (LookupError, ValueError):
        await callback.message.answer("Не удалось сохранить знак. Попробуйте ещё раз.")
        return
    await _show(callback.message, state, preference, daily_snapshots)
