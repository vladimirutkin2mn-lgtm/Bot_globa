"""One-tap focuses for the personal astrology view of today's day.

These callbacks reuse the astrologer's normal generation path. A preset focus contains
only server-authored safe text; free-form input stays in the regular question state and
therefore keeps the existing safety middleware.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import horoscope_flow as flow
from app.bot import horoscope_intent
from app.bot.consent import ensure_consent
from app.bot.horoscope_handlers import HoroscopeHandlers
from app.bot.horoscope_renderer import HoroscopeRenderer
from app.bot.persona_flow import QUESTION_PROMPT
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.bot.states import HoroscopeStates
from app.services.horoscope_reading import HoroscopeReadingUseCase
from app.services.onboarding import OnboardingService
from app.services.oracle_memory import OracleMemoryService

router = Router(name="daily_personal_topics")
_FOCUS_PREFIX = flow.callback("day", "focus", "")
_CUSTOM_CALLBACK = flow.callback("day", "custom")


def is_personal_day_context(data: dict[str, object]) -> bool:
    """Reject stale day buttons if the live Astro intake belongs to another topic."""

    return data.get("topic") == horoscope_intent.DAY_FORECAST_INTENT


async def _restore_current_question(message: Message, state: FSMContext) -> None:
    """Keep the current Astro topic intact when an old personal-day button is pressed."""

    await show_screen(
        message,
        Scene.QUESTION,
        QUESTION_PROMPT,
        reply_markup=flow.HOROSCOPE_FLOW.question_keyboard(),
        state=state,
    )


@router.callback_query(HoroscopeStates.waiting_for_question, F.data.startswith(_FOCUS_PREFIX))
async def choose_personal_day_focus(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    horoscope_use_case: HoroscopeReadingUseCase,
    horoscope_renderer: HoroscopeRenderer,
    reading_full_price_label: str,
    privacy_retention_days: int,
    oracle_memory: OracleMemoryService | None = None,
) -> None:
    """Generate the normal day forecast from a safe one-tap focus."""

    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if not await ensure_consent(
        callback.message,
        callback.from_user.id,
        state,
        onboarding,
        privacy_retention_days,
        destination=flow.HOROSCOPE_FLOW.namespace,
    ):
        return

    if not is_personal_day_context(await state.get_data()):
        await _restore_current_question(callback.message, state)
        return

    focus = (callback.data or "").removeprefix(_FOCUS_PREFIX)
    question = horoscope_intent.PERSONAL_DAILY_FOCUS_QUESTIONS.get(focus)
    if question is None:
        await show_screen(
            callback.message,
            Scene.QUESTION,
            horoscope_intent.PERSONAL_DAILY_PROMPT,
            reply_markup=horoscope_intent.personal_daily_keyboard(),
            state=state,
        )
        return

    await state.update_data(question=question)
    await HoroscopeHandlers()._generate(
        callback.message,
        callback.from_user.id,
        state,
        onboarding,
        horoscope_use_case,
        horoscope_renderer,
        context=None,
        price_label=reading_full_price_label,
        oracle_memory=oracle_memory,
    )


@router.callback_query(HoroscopeStates.waiting_for_question, F.data == _CUSTOM_CALLBACK)
async def ask_custom_personal_day_question(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Switch from one-tap focuses to the existing free-form safety-checked intake."""

    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if not is_personal_day_context(await state.get_data()):
        await _restore_current_question(callback.message, state)
        return
    await _restore_current_question(callback.message, state)
