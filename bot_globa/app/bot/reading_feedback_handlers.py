"""Privacy-safe quick feedback for a paid reading."""

from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.persona_flow import FEEDBACK_NAMESPACE
from app.bot.reading_share_handlers import router as reading_share_router
from app.providers.analytics import OracleProductEvent
from app.services.onboarding import OnboardingService
from app.services.oracle_product_analytics import OracleProductAnalytics
from app.services.reading_history import ReadingHistoryService

router = Router(name="reading-feedback")
router.include_router(reading_share_router)


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
    reaction, reading_id = parsed
    if not await reading_history.owns_full(user.id, reading_id):
        await callback.answer("Разбор недоступен.", show_alert=True)
        return
    await oracle_analytics.track(
        user.id,
        OracleProductEvent.READING_FEEDBACK_SUBMITTED,
        {"reading_id": reading_id, "reaction_code": reaction},
    )
    await callback.answer("Спасибо, это поможет улучшить разбор.")


def _parse(data: str | None) -> tuple[str, UUID] | None:
    parts = (data or "").split(":", 2)
    if len(parts) != 3 or parts[0] != FEEDBACK_NAMESPACE or parts[1] not in {"hit", "miss"}:
        return None
    try:
        return parts[1], UUID(parts[2])
    except ValueError:
        return None
