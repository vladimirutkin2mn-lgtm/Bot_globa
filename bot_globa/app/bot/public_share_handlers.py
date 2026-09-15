"""Public, privacy-safe share paths for Numa's free audience.

The daily card contains only the common date/theme already shown to every user. Referral
links carry a campaign code only: no sender, recipient, Telegram, reading or birth data.
This router also wraps the existing paid-insight landing so recipient acquisition is
recorded in the same typed Numa funnel without duplicating its UI behavior.
"""

import logging
from urllib.parse import quote, urlencode
from uuid import UUID, uuid5

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.daily_keyboards import DAILY_SHARE_CALLBACK
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
DAILY_SHARE_CONFIRM_CALLBACK = "pubshare:daily:confirm"

DAILY_SHARE_PREVIEW_PREFIX = "📤 Перед отправкой проверьте точный текст:\n\n"
DAILY_SHARE_PREVIEW_SUFFIX = (
    "\n\nЭто весь публичный текст. Личный профиль, история и ваши вопросы не добавятся."
)
DAILY_SHARE_READY = "Текст подтверждён. Нажмите «Выбрать чат» — Telegram откроет меню отправки."
DAILY_SHARE_UNAVAILABLE = (
    "Не получилось подготовить тему дня. Откройте гороскоп и попробуйте ещё раз."
)
DAILY_SHARE_LANDING = (
    "🌙 <b>Вам прислали тему дня из Numa</b>\n\n"
    "Это общая тема сегодняшнего гороскопа. Откройте свой прогноз — если знак ещё не выбран, "
    "Numa сначала предложит выбрать его."
)


def render_daily_public_share(source_text: str) -> str:
    """Keep only the public date and common theme, even from a sign-specific message."""

    lines = [line.strip() for line in source_text.splitlines() if line.strip()]
    title = next((line for line in lines if line.startswith("Гороскоп на сегодня · ")), None)
    theme = next((line for line in lines if line.startswith("🌙 Тема дня: ")), None)
    if title is None or theme is None:
        raise ValueError("daily public share source is not a rendered daily horoscope")
    return f"{title}\n{theme}\n\n— Numa"


def render_daily_share_preview(public_text: str) -> str:
    """Show exactly what can become public before the user confirms it."""

    if not public_text.strip():
        raise ValueError("daily public share text is empty")
    return f"{DAILY_SHARE_PREVIEW_PREFIX}{public_text}{DAILY_SHARE_PREVIEW_SUFFIX}"


def extract_confirmed_daily_share(preview_text: str) -> str:
    """Recover only text that was explicitly shown by the confirmation screen."""

    if not preview_text.startswith(DAILY_SHARE_PREVIEW_PREFIX) or not preview_text.endswith(
        DAILY_SHARE_PREVIEW_SUFFIX
    ):
        raise ValueError("daily share confirmation is not a known preview")
    public_text = preview_text[len(DAILY_SHARE_PREVIEW_PREFIX) : -len(DAILY_SHARE_PREVIEW_SUFFIX)]
    if not public_text.strip():
        raise ValueError("daily share confirmation is empty")
    return public_text


def build_daily_telegram_share_url_from_public_text(bot_username: str, public_text: str) -> str:
    """Build a share URL only after the exact public text has been confirmed."""

    username = bot_username.removeprefix("@").strip()
    if not username:
        raise ValueError("bot username is required for sharing")
    if not public_text.strip():
        raise ValueError("public text is required for sharing")
    referral = f"https://t.me/{username}?start={DAILY_SHARE_ENTRY_PAYLOAD}"
    return "https://t.me/share/url?" + urlencode(
        {"url": referral, "text": public_text},
        quote_via=quote,
    )


def build_daily_telegram_share_url(bot_username: str, source_text: str) -> str:
    """Build an aggregate daily referral with no user or reading identifier."""

    return build_daily_telegram_share_url_from_public_text(
        bot_username,
        render_daily_public_share(source_text),
    )


def daily_share_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить текст",
                    callback_data=DAILY_SHARE_CONFIRM_CALLBACK,
                )
            ],
            [InlineKeyboardButton(text="← К гороскопу", callback_data="menu:daily")],
        ]
    )


def daily_share_landing_keyboard() -> InlineKeyboardMarkup:
    """Take a recipient into the scenario they were actually shown."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="☀️ Мой прогноз на сегодня", callback_data="menu:daily")]
        ]
    )


@router.callback_query(F.data == DAILY_SHARE_CALLBACK)
async def share_daily_public_card(callback: CallbackQuery) -> None:
    """Preview the exact public card; sharing is impossible until explicit confirmation."""

    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    source_text = callback.message.text or callback.message.caption or ""
    try:
        public_text = render_daily_public_share(source_text)
        preview_text = render_daily_share_preview(public_text)
    except ValueError:
        await callback.message.answer(DAILY_SHARE_UNAVAILABLE)
        return

    await callback.message.answer(
        preview_text,
        reply_markup=daily_share_preview_keyboard(),
        parse_mode=None,
    )


@router.callback_query(F.data == DAILY_SHARE_CONFIRM_CALLBACK)
async def confirm_daily_public_card(
    callback: CallbackQuery,
    bot: Bot,
    onboarding: OnboardingService,
    numa_product_analytics: NumaProductAnalytics,
) -> None:
    """Only an explicitly confirmed preview receives a native Telegram share button."""

    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    try:
        public_text = extract_confirmed_daily_share(callback.message.text or "")
        bot_user = await bot.get_me()
        if not bot_user.username:
            raise ValueError("bot username is unavailable")
        share_url = build_daily_telegram_share_url_from_public_text(bot_user.username, public_text)
    except (TelegramAPIError, ValueError):
        await callback.answer("Не получилось подтвердить этот текст.", show_alert=True)
        return

    await callback.answer("Текст подтверждён")
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
        reply_markup=daily_share_landing_keyboard(),
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
