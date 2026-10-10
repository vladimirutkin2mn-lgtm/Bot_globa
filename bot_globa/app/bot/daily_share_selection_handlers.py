"""Observe the closest Telegram signal to a completed daily-share send action.

Telegram's `chosen_inline_result` means the user selected Numa's inline card from the
picker. It is not a delivery receipt, so analytics names this step `share_selected` rather
than `share_sent`. No Telegram ids, recipient/chat data, or message content are stored.
"""

import logging
from uuid import uuid5

from aiogram import F, Router
from aiogram.types import ChosenInlineResult

from app.bot.public_share_handlers import (
    DAILY_SHARE_FORMAT,
    DAILY_SHARE_SCENARIO,
    parse_daily_share_inline_query,
)
from app.providers.numa_product_analytics import ProductFlow, ProductFunnelEvent, ProductSource
from app.services.numa_product_analytics import NumaProductAnalytics, ProductAttribution
from app.services.onboarding import OnboardingService

logger = logging.getLogger(__name__)

router = Router(name="daily-share-selection")


@router.chosen_inline_result(F.query.startswith("daily"))
async def track_daily_share_selection(
    chosen: ChosenInlineResult,
    onboarding: OnboardingService,
    numa_product_analytics: NumaProductAnalytics,
) -> None:
    """Record only a dated aggregate selection after the inline result is chosen."""

    forecast_date = parse_daily_share_inline_query(chosen.query)
    if forecast_date is None:
        return
    user = await onboarding.current_user(chosen.from_user.id)
    if user is None:
        return
    entity_id = uuid5(user.id, f"daily-share-selected:{forecast_date.isoformat()}")
    try:
        await numa_product_analytics.track(
            user_id=user.id,
            entity_id=entity_id,
            event=ProductFunnelEvent.SHARE_SELECTED,
            attribution=ProductAttribution(
                flow=ProductFlow.DAILY,
                source=ProductSource.DAILY_HOROSCOPE,
                scenario_version=DAILY_SHARE_SCENARIO,
            ),
            properties={"share_format": DAILY_SHARE_FORMAT},
        )
    except Exception:
        logger.warning("numa_daily_share_analytics_failed event=share_selected")
