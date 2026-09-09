"""One-tap usefulness feedback for the common daily horoscope."""

from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.daily_horoscope import (
    DAILY_FEEDBACK_CLOSED,
    DAILY_FEEDBACK_THANKS,
    render_daily_feedback_settings,
)
from app.bot.keyboards import daily_feedback_settings_keyboard
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.domain.daily_horoscope import DailyHoroscopeFeedbackAnswer
from app.services.daily_horoscope import DailyHoroscopePreferenceService
from app.services.onboarding import OnboardingService

router = Router(name="daily_feedback")
_PREFIX = "daily:feedback:"
_SETTING_PREFIX = "daily:feedback-setting:"


@router.callback_query(F.data == "daily:feedback-settings")
async def daily_feedback_settings(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    daily_horoscopes: DailyHoroscopePreferenceService,
) -> None:
    """Explain the optional evening question before the user opts in."""

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
        render_daily_feedback_settings(preference.feedback_enabled),
        reply_markup=daily_feedback_settings_keyboard(preference.feedback_enabled),
        state=state,
    )


@router.callback_query(F.data.startswith(_SETTING_PREFIX))
async def set_daily_feedback_setting(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    daily_horoscopes: DailyHoroscopePreferenceService,
) -> None:
    """Persist a deliberate opt-in or opt-out for the evening usefulness prompt."""

    value = (callback.data or "").removeprefix(_SETTING_PREFIX)
    if value not in {"on", "off"}:
        await callback.answer("Не удалось сохранить настройку.")
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала отправьте /start.")
        return
    try:
        preference = await daily_horoscopes.set_feedback_enabled(user.id, value == "on")
    except LookupError:
        await callback.answer("Не удалось сохранить настройку.")
        return
    await callback.answer("Готово")
    if isinstance(callback.message, Message):
        await show_screen(
            callback.message,
            Scene.DAILY_SETTINGS,
            render_daily_feedback_settings(preference.feedback_enabled),
            reply_markup=daily_feedback_settings_keyboard(preference.feedback_enabled),
            state=state,
        )


@router.callback_query(F.data.startswith(_PREFIX))
async def submit_daily_horoscope_feedback(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    daily_horoscopes: DailyHoroscopePreferenceService,
) -> None:
    """Record only the first answer for a feedback prompt that was actually delivered."""

    parsed = _parse_feedback_callback(callback.data)
    if parsed is None:
        await callback.answer(DAILY_FEEDBACK_CLOSED)
        return
    answer, forecast_date = parsed
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await callback.answer(DAILY_FEEDBACK_CLOSED)
        return

    saved = await daily_horoscopes.submit_feedback(user.id, forecast_date, answer)
    await callback.answer(DAILY_FEEDBACK_THANKS if saved else DAILY_FEEDBACK_CLOSED)
    if saved and isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)


def _parse_feedback_callback(
    data: str | None,
) -> tuple[DailyHoroscopeFeedbackAnswer, date] | None:
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[:2] != ["daily", "feedback"]:
        return None
    try:
        return DailyHoroscopeFeedbackAnswer(parts[2]), date.fromisoformat(parts[3])
    except ValueError:
        return None
