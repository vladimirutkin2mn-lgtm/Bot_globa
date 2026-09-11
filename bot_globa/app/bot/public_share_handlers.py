"""Public, privacy-safe share paths for Numa's free audience.

The daily card contains only the common date/theme already shown to every user. Referral
links carry a campaign code only: no sender, recipient, Telegram, reading or birth data.
This router also wraps the existing paid-insight landing so recipient acquisition is
recorded in the same typed Numa funnel without duplicating its UI behavior.
"""

import logging
from urllib.parse import urlencode
from uuid import UUID, uuid5

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.daily_keyboards import DAILY_SHARE_CALLBACK
from app.bot.keyboards import main_menu_keyboard
from app.bot.reading_share_handlers import (
    SHARE_ENTRY_PAYLOAD,
    SHARE_RENDERER_VERSION,
    open_share_referral,
)
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.providers.numa_product_analytics import ProductFlow, ProductFunnelEvent, ProductSource
from app.services.numa_product_analytics import NumaProductAnalytics, ProductAttribution
from app.services.onboarding import OnboardingService, TelegramIdentity

logger = logging.getLogger(__name__)

router = Router(name="public-share")

DAILY_SHARE_ENTRY_PAYLOAD = "share_day"
DAILY_SHARE_FORMAT = "daily_public_card_v1"
DAILY_SHARE_SCENARIO = "daily_public_share_v1"
DAILY_SHARE_CAMPAIGN = "daily_public_card_v1"
PERSONAL_SHARE_CAMPAIGN = "personal_insight_card_v1"

DAILY_SHARE_READY = "Тема дня готова. Нажмите «Выбрать чат» — Telegram откроет меню отправки."
DAILY_SHARE_UNAVAILABLE = "Не получилось подготовить тему дня. Откройте гороскоп и попробуйте ещё раз."
DAILY_SHARE_LANDING = (
    "🌙 <b>Вам прислали тему дня из Numa</b>\n\n"
    "В Numa есть общий гороскоп на день, личные разборы и групповые сценарии. "
    "Можно начать с сегодняшнего прогноза или задать свой вопрос."
)


def render_daily_public_share(source_text: str) -> str:
    """Keep only the public date and common theme, even from a sign-specific message."""

    lines = [line.strip() for line in source_text.splitlines() if line.strip()]
    title = next((line for line in lines if line.startswith("Гороскоп на сегодня · ")), None)
    theme = next((line for line in lines if line.startswith("🌙 Тема дня: ")), None)
    if title is None or theme is None:
        raise ValueError("daily public share source is not a rendered daily horoscope")
    return f"{title}\n{theme}\n\n— Numa"


def build_daily_telegram_share_url(bot_username: str, source_text: str) -> str:
    """Build an aggregate daily referral with no user or reading identifier."""

    username = bot_username.removeprefix("@").strip()
    if not username:
        raise ValueError("bot username is required for sharing")
    referral = f"https://t.me/{username}?start={DAILY_SHARE_ENTRY_PAYLOAD}"
    return "https://t.me/share/url?" + urlencode(
        {
            "url": referral,
            "text": render_daily_public_share(source_text),
        }
    )


@router.callback_query(F.data == DAILY_SHARE_CALLBACK)
async def share_daily_public_card(
    callback: CallbackQuery,
    bot: Bot,
    onboarding: OnboardingService,
    numa_product_analytics: NumaProductAnalytics,
) -> None:
    """Hand off the common day card to Telegram's native share picker."""

    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    source_text = callback.message.text or callback.message.caption or ""
    try:
        public_text = render_daily_public_share(source_text)
        bot_user = await bot.get_me()
        if not bot_user.username:
            raise ValueError("bot username is unavailable")
        share_url = build_daily_telegram_share_url(bot_user.username, source_text)
    except (TelegramAPIError, ValueError):
        await callback.message.answer(DAILY_SHARE_UNAVAILABLE)
        return

    user = await onboarding.current_user(callback.from_user.id)
    if user is not None:
        await _track_share_intent(numa_product_analytics, user.id, public_text)

    await callback.message.answer(
        DAILY_SHARE_READY,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📤 Выбрать чат", url=share_url)],
                [InlineKeyboardButton(text="← К гороскопу", callback_data="menu:daily")],
            ]
        ),
    )


@router.message(CommandStart(deep_link=True, magic=F.args == DAILY_SHARE_ENTRY_PAYLOAD))
async def open_daily_share_referral(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    numa_product_analytics: NumaProductAnalytics,
) -> None:
    """Land a daily-card recipient and record aggregate acquisition only."""

    if message.from_user is None:
        return
    user, _ = await onboarding.start(_telegram_identity(message))
    await _track_recipient_entry(
        numa_product_analytics,
        user.id,
        flow=ProductFlow.DAILY,
        source=ProductSource.SHARED_DAILY,
        scenario_version=DAILY_SHARE_SCENARIO,
        campaign_code=DAILY_SHARE_CAMPAIGN,
    )
    await state.clear()
    await show_screen(
        message,
        Scene.MAIN_MENU,
        DAILY_SHARE_LANDING,
        reply_markup=main_menu_keyboard(),
        state=state,
    )


@router.message(CommandStart(deep_link=True, magic=F.args == SHARE_ENTRY_PAYLOAD))
async def open_paid_share_referral_with_attribution(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    numa_product_analytics: NumaProductAnalytics,
) -> None:
    """Reuse the paid-share landing and add the typed recipient-entry event around it."""

    await open_share_referral(message, state, onboarding)
    if message.from_user is None:
        return
    user = await onboarding.current_user(message.from_user.id)
    if user is None:
        return
    await _track_recipient_entry(
        numa_product_analytics,
        user.id,
        flow=ProductFlow.PERSONAL,
        source=ProductSource.SHARED_INSIGHT,
        scenario_version=SHARE_RENDERER_VERSION,
        campaign_code=PERSONAL_SHARE_CAMPAIGN,
    )


async def _track_share_intent(
    analytics: NumaProductAnalytics,
    user_id: UUID,
    public_text: str,
) -> None:
    entity_id = uuid5(user_id, f"daily-share:{public_text}")
    try:
        await analytics.track(
            user_id=user_id,
            entity_id=entity_id,
            event=ProductFunnelEvent.SHARE_INTENT,
            attribution=ProductAttribution(
                flow=ProductFlow.DAILY,
                source=ProductSource.DAILY_HOROSCOPE,
                scenario_version=DAILY_SHARE_SCENARIO,
            ),
            properties={"share_format": DAILY_SHARE_FORMAT},
        )
    except Exception:
        logger.warning("numa_daily_share_analytics_failed event=share_intent")


async def _track_recipient_entry(
    analytics: NumaProductAnalytics,
    user_id: UUID,
    *,
    flow: ProductFlow,
    source: ProductSource,
    scenario_version: str,
    campaign_code: str,
) -> None:
    entity_id = uuid5(user_id, f"share-recipient:{campaign_code}")
    try:
        await analytics.track(
            user_id=user_id,
            entity_id=entity_id,
            event=ProductFunnelEvent.RECIPIENT_ENTRY,
            attribution=ProductAttribution(
                flow=flow,
                source=source,
                scenario_version=scenario_version,
            ),
            properties={"campaign_code": campaign_code},
        )
    except Exception:
        logger.warning("numa_share_analytics_failed event=recipient_entry source=%s", source.value)


def _telegram_identity(message: Message) -> TelegramIdentity:
    telegram_user = message.from_user
    if telegram_user is None:
        raise ValueError("share referral requires a Telegram user")
    return TelegramIdentity(
        telegram_user_id=telegram_user.id,
        username=telegram_user.username,
        first_name=telegram_user.first_name,
        language=telegram_user.language_code,
    )
