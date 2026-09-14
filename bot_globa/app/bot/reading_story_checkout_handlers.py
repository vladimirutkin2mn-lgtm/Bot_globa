"""Resume a story-started reading through checkout without losing its target story."""

from collections.abc import Mapping
from uuid import UUID

from aiogram import Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import texts
from app.bot.horoscope_flow import HOROSCOPE_FLOW
from app.bot.horoscope_handlers import HoroscopeHandlers
from app.bot.horoscope_renderer import HoroscopeRenderer
from app.bot.keyboards import products_keyboard
from app.bot.persona_flow import PersonaReadingBundle
from app.bot.persona_flows import MVP_READING_FLOWS
from app.bot.persona_handlers import PersonaReadingHandlers
from app.bot.scene_media import Scene
from app.bot.screen import show_screen, show_thinking
from app.config import Settings
from app.domain.billing import BillingCatalog
from app.domain.reading_checkout_resume import (
    ReadingCheckoutTarget,
    parse_reading_resume_callback,
)
from app.services.horoscope_reading import HoroscopeReadingUseCase
from app.services.monetized_reading import MonetizedReadingService, MonetizedReadingStatus
from app.services.onboarding import OnboardingService
from app.services.oracle_memory import OracleMemoryService

router = Router(name="reading-story-checkout")

_PERSONA_FLOWS = {flow.persona_code: flow for flow in MVP_READING_FLOWS}


class StoryReadingCheckoutFilter(BaseFilter):
    """Match only durable unlock callbacks that carry an explicit story target."""

    async def __call__(self, callback: CallbackQuery) -> dict[str, ReadingCheckoutTarget] | bool:
        target = parse_reading_resume_callback(callback.data)
        if target is None or target.story_id is None:
            return False
        return {"story_checkout_target": target}


@router.callback_query(StoryReadingCheckoutFilter())
async def resume_story_reading(
    callback: CallbackQuery,
    state: FSMContext,
    story_checkout_target: ReadingCheckoutTarget,
    onboarding: OnboardingService,
    persona_readings: Mapping[str, PersonaReadingBundle],
    billing_catalog: BillingCatalog,
    billing_settings: Settings,
    horoscope_use_case: HoroscopeReadingUseCase,
    horoscope_monetized: MonetizedReadingService,
    horoscope_renderer: HoroscopeRenderer,
    reading_full_price_label: str,
    oracle_memory: OracleMemoryService | None = None,
) -> None:
    """Use the normal unlock services while preserving the story across a paywall."""

    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await state.clear()
        await callback.message.answer("Сначала отправьте /start.")
        return

    if story_checkout_target.persona_code == HOROSCOPE_FLOW.persona_code:
        await _resume_astrology(
            callback.message,
            state,
            story_checkout_target,
            user.id,
            horoscope_use_case,
            horoscope_monetized,
            horoscope_renderer,
            billing_catalog,
            billing_settings,
            reading_full_price_label,
            oracle_memory,
        )
        return

    flow = _PERSONA_FLOWS.get(story_checkout_target.persona_code)
    bundle = persona_readings.get(story_checkout_target.persona_code)
    if flow is None or bundle is None:
        await callback.message.answer("Этот разбор уже недоступен.")
        return

    handlers = PersonaReadingHandlers(flow)
    reading_id = story_checkout_target.reading_id
    await show_screen(callback.message, Scene.UNLOCKING, "Открываю полный разбор…", state=state)
    await show_thinking(callback.message)
    unlocked = await bundle.monetized.unlock_full(reading_id, user.id)
    if unlocked.status is MonetizedReadingStatus.INSUFFICIENT_CREDITS:
        await show_screen(
            callback.message,
            Scene.INSUFFICIENT_CREDITS,
            texts.PAYWALL.format(price=bundle.full_price_label),
            state=state,
            reply_markup=products_keyboard(
                billing_catalog,
                billing_settings,
                resume_callback=story_checkout_target.callback_data,
            ),
        )
        return
    if unlocked.status is MonetizedReadingStatus.FULL_COMPLETED:
        outcome = await handlers._generated(
            bundle.use_case.generate_existing_preview(reading_id, user.id)
        )
        if outcome is not None:
            await handlers._deliver(
                callback.message,
                state,
                outcome,
                bundle,
                user.id,
                continuation_story_id=story_checkout_target.story_id,
            )
            return
    await show_screen(
        callback.message,
        Scene.GENERATION_FAILED,
        flow.texts.unlock_failed,
        state=state,
        reply_markup=flow.result_keyboard(),
    )


async def _resume_astrology(
    message: Message,
    state: FSMContext,
    target: ReadingCheckoutTarget,
    user_id: UUID,
    use_case: HoroscopeReadingUseCase,
    monetized: MonetizedReadingService,
    renderer: HoroscopeRenderer,
    billing_catalog: BillingCatalog,
    billing_settings: Settings,
    price_label: str,
    oracle_memory: OracleMemoryService | None,
) -> None:
    reading_id = target.reading_id
    await show_screen(message, Scene.UNLOCKING, "Открываю полный разбор…", state=state)
    unlocked = await monetized.unlock_full(reading_id, user_id)
    if unlocked.status is MonetizedReadingStatus.INSUFFICIENT_CREDITS:
        await show_screen(
            message,
            Scene.INSUFFICIENT_CREDITS,
            texts.PAYWALL.format(price=price_label),
            state=state,
            reply_markup=products_keyboard(
                billing_catalog,
                billing_settings,
                resume_callback=target.callback_data,
            ),
        )
        return
    if unlocked.status is MonetizedReadingStatus.FULL_COMPLETED:
        outcome = await use_case.generate_existing_preview(reading_id, user_id)
        await HoroscopeHandlers()._deliver(
            message,
            state,
            outcome,
            renderer,
            price_label,
            user_id=user_id,
            oracle_memory=oracle_memory,
            continuation_story_id=target.story_id,
        )
        return
    await show_screen(
        message,
        Scene.GENERATION_FAILED,
        HOROSCOPE_FLOW.texts.unlock_failed,
        state=state,
        reply_markup=HOROSCOPE_FLOW.result_keyboard(),
    )
