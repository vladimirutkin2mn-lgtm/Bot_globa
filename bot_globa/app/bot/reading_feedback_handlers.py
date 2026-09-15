"""Privacy-safe quick feedback for a ready reading."""

import logging
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.persona_flow import FEEDBACK_NAMESPACE, feedback_reason_keyboard
from app.bot.public_share_handlers import router as public_share_router
from app.bot.reading_share_handlers import (
    SHARE_PROMPT,
    share_offer_keyboard,
)
from app.bot.reading_share_handlers import (
    router as reading_share_router,
)
from app.domain.reading import ReadingStatus
from app.providers.analytics import OracleProductEvent
from app.services.onboarding import OnboardingService
from app.services.oracle_product_analytics import OracleProductAnalytics
from app.services.reading_history import ReadingHistoryService

logger = logging.getLogger(__name__)

router = Router(name="reading-feedback")
router.include_router(public_share_router)
router.include_router(reading_share_router)

_FINAL_REACTIONS = {
    "hit": "hit",
    "miss_plain": "miss",
    "miss_too_general": "miss_too_general",
    "miss_off_question": "miss_off_question",
    "miss_unclear": "miss_unclear",
}

FEEDBACK_RECOVERY_TEXT = (
    "Понял. Не обязательно оставаться с неудачным ответом — можно сразу попробовать другой формат."
)


def feedback_recovery_keyboard() -> InlineKeyboardMarkup:
    """Offer a concrete next step after a miss instead of ending the journey."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Новый расклад", callback_data="menu:tarot")],
            [InlineKeyboardButton(text="🧠 Разобрать ситуацию", callback_data="menu:psy")],
            [InlineKeyboardButton(text="🪐 Спросить астролога", callback_data="menu:astro")],
        ]
    )


@router.callback_query(F.data.startswith(f"{FEEDBACK_NAMESPACE}:"))
async def submit_reading_feedback(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    reading_history: ReadingHistoryService,
    oracle_analytics: OracleProductAnalytics,
) -> None:
    parsed = _parse(callback.data)
    user = await onboarding.current_user(callback.from_user.id)
    if parsed is None or user is None:
        await callback.answer("Разбор недоступен.", show_alert=True)
        return
    action, reading_id = parsed
    if not await reading_history.owns_ready(user.id, reading_id):
        await callback.answer("Разбор недоступен.", show_alert=True)
        return

    if action == "miss":
        if isinstance(callback.message, Message):
            await callback.message.answer(
                "Что было не так? Можно выбрать причину или пропустить.",
                reply_markup=feedback_reason_keyboard(reading_id),
            )
        await callback.answer()
        return

    reaction = _FINAL_REACTIONS[action]
    stage_code = await _feedback_stage_code(reading_history, user.id, reading_id)
    await oracle_analytics.track(
        user.id,
        OracleProductEvent.READING_FEEDBACK_SUBMITTED,
        {
            "reaction_code": reaction,
            "reading_id": str(reading_id),
            "stage_code": stage_code,
        },
    )
    await callback.answer("Спасибо, это поможет улучшить разбор.")

    if not isinstance(callback.message, Message):
        return

    if action == "hit" and await reading_history.owns_full(user.id, reading_id):
        await callback.message.answer(
            SHARE_PROMPT,
            reply_markup=share_offer_keyboard(reading_id),
        )
        return

    if action != "hit":
        await callback.message.answer(
            FEEDBACK_RECOVERY_TEXT,
            reply_markup=feedback_recovery_keyboard(),
        )


async def _feedback_stage_code(
    reading_history: ReadingHistoryService,
    user_id: UUID,
    reading_id: UUID,
) -> str:
    """Resolve safe server-side stage metadata without blocking feedback on lookup errors."""

    try:
        metadata = await reading_history.ready_metadata(user_id, (reading_id,))
    except Exception:
        logger.warning("reading_feedback_metadata_lookup_failed", exc_info=True)
        return "unknown"

    if not metadata:
        return "unknown"
    return {
        ReadingStatus.PREVIEW_READY.value: "preview",
        ReadingStatus.FULL_READY.value: "full",
    }.get(metadata[0].status, "unknown")


def _parse(data: str | None) -> tuple[str, UUID] | None:
    parts = (data or "").split(":", 2)
    allowed = {*_FINAL_REACTIONS, "miss"}
    if len(parts) != 3 or parts[0] != FEEDBACK_NAMESPACE or parts[1] not in allowed:
        return None
    try:
        return parts[1], UUID(parts[2])
    except ValueError:
        return None
