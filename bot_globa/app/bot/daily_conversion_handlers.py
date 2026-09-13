"""Conversion bridge from the common daily digest into a personal day forecast."""

import logging
from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import horoscope_flow as flow
from app.bot import horoscope_intent
from app.bot.consent import ensure_consent
from app.bot.daily_keyboards import DAILY_PERSONAL_CALLBACK
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.bot.states import HoroscopeStates
from app.domain.birth_profile import BirthProfileConsentStatus
from app.providers.analytics import OracleProductEvent
from app.services.birth_profile import BirthProfileConsentRequiredError, BirthProfileService
from app.services.daily_horoscope import DailyHoroscopePreferenceService
from app.services.numa_daily_analytics import NumaDailyAnalytics
from app.services.numa_product_analytics import NumaProductAnalytics
from app.services.onboarding import OnboardingService
from app.services.oracle_product_analytics import OracleProductAnalytics

logger = logging.getLogger(__name__)
router = Router(name="daily_conversion")

# Backwards-compatible import surface for tests/templates that reference the prompt here.
PERSONAL_DAILY_PROMPT = horoscope_intent.PERSONAL_DAILY_PROMPT


@router.callback_query(
    (F.data == DAILY_PERSONAL_CALLBACK) | F.data.startswith(f"{DAILY_PERSONAL_CALLBACK}:")
)
async def open_personal_daily(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
    privacy_retention_days: int,
    oracle_analytics: OracleProductAnalytics | None = None,
    numa_product_analytics: NumaProductAnalytics | None = None,
    daily_horoscopes: DailyHoroscopePreferenceService | None = None,
) -> None:
    """Continue the free digest into the existing Astrologer day-forecast funnel."""

    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    # Store the source intent before either consent gate changes the FSM state. Production
    # uses PostgreSQL FSM storage, so this small code also survives worker restarts.
    await horoscope_intent.remember_horoscope_intent(
        state,
        horoscope_intent.DAY_FORECAST_INTENT,
    )
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

    logger.info("daily_horoscope_personal_cta_clicked")
    delivery_date = _delivery_date(callback.data)
    if (
        delivery_date is not None
        and numa_product_analytics is not None
        and daily_horoscopes is not None
    ):
        try:
            preference = await daily_horoscopes.current(user.id)
            await NumaDailyAnalytics(numa_product_analytics).action(
                user.id,
                delivery_date,
                preference.timezone,
                "personal_forecast_cta",
            )
        except Exception:
            # Conversion must keep working even when telemetry or preference lookup fails.
            logger.warning("daily_horoscope_analytics_failed event=daily_action")

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

    if not await horoscope_intent.resume_horoscope_intent(callback.message, state):
        # Defensive fallback: the intent was written in this handler, so reaching this
        # branch means storage was externally cleared between reads.
        await state.clear()
        await callback.message.answer(
            "Не удалось восстановить персональный прогноз. Попробуйте ещё раз."
        )


def _delivery_date(callback_data: str | None) -> date | None:
    """Extract only the server-generated scheduled-digest date; legacy callbacks stay valid."""

    if callback_data is None or callback_data == DAILY_PERSONAL_CALLBACK:
        return None
    prefix = f"{DAILY_PERSONAL_CALLBACK}:"
    if not callback_data.startswith(prefix):
        return None
    try:
        return date.fromisoformat(callback_data.removeprefix(prefix))
    except ValueError:
        return None
