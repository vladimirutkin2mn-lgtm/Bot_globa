"""Conversion bridge from the common daily digest into a personal day forecast."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import horoscope_flow as flow
from app.bot.consent import ensure_consent
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.bot.states import HoroscopeStates
from app.domain.birth_profile import BirthProfileConsentStatus
from app.providers.analytics import OracleProductEvent
from app.services.birth_profile import BirthProfileConsentRequiredError, BirthProfileService
from app.services.onboarding import OnboardingService
from app.services.oracle_product_analytics import OracleProductAnalytics

router = Router(name="daily_conversion")

PERSONAL_DAILY_PROMPT = (
    "✨ Персональный прогноз на сегодня\n\n"
    "Что для вас сегодня важнее всего: отношения, работа, деньги или общее направление? "
    "Можно задать свой вопрос."
)


@router.callback_query(F.data == "daily:personal")
async def open_personal_daily(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
    privacy_retention_days: int,
    oracle_analytics: OracleProductAnalytics | None = None,
) -> None:
    """Continue the free digest into the existing Astrologer day-forecast funnel."""

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
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await state.clear()
        await callback.message.answer("Сначала отправьте /start.")
        return

    if oracle_analytics is not None:
        await oracle_analytics.track(
            user.id,
            OracleProductEvent.PERSONA_SELECTED,
            {
                "persona_code": flow.HOROSCOPE_FLOW.persona_code,
                "topic_code": "day_forecast",
            },
        )

    consent = await birth_profile_service.consent_state(user.id)
    if consent is None or consent.status is not BirthProfileConsentStatus.GRANTED:
        await state.set_state(HoroscopeStates.waiting_for_consent)
        await show_screen(
            callback.message,
            Scene.ASTRO_CONSENT,
            flow.CONSENT,
            reply_markup=flow.consent_keyboard(),
            state=state,
        )
        return

    try:
        profile = await birth_profile_service.load(user.id)
    except BirthProfileConsentRequiredError:
        await state.set_state(HoroscopeStates.waiting_for_consent)
        await show_screen(
            callback.message,
            Scene.ASTRO_CONSENT,
            flow.CONSENT,
            reply_markup=flow.consent_keyboard(),
            state=state,
        )
        return

    if profile is None:
        await state.set_state(HoroscopeStates.waiting_for_birth_date)
        await show_screen(
            callback.message,
            Scene.ASTRO_BIRTH_DATE,
            flow.BIRTH_DATE_PROMPT,
            reply_markup=flow.cancel_keyboard(),
            state=state,
        )
        return

    await state.update_data(topic="day_forecast")
    await state.set_state(HoroscopeStates.waiting_for_question)
    await show_screen(
        callback.message,
        Scene.QUESTION,
        PERSONAL_DAILY_PROMPT,
        reply_markup=flow.HOROSCOPE_FLOW.question_keyboard(),
        state=state,
    )
