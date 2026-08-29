"""One-tap usefulness feedback for the common daily horoscope."""

from datetime import date

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.daily_horoscope import DAILY_FEEDBACK_CLOSED, DAILY_FEEDBACK_THANKS
from app.domain.daily_horoscope import DailyHoroscopeFeedbackAnswer
from app.services.daily_horoscope import DailyHoroscopePreferenceService
from app.services.onboarding import OnboardingService

router = Router(name="daily_feedback")
_PREFIX = "daily:feedback:"


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
