"""Privacy-safe sharing for a paid personal reading.

The generated reading already contains a dedicated `share_card` payload. This transport
layer never copies the user's question, full result or reading id into a public URL. The
owner sees the exact card before opening Telegram's share picker, and only aggregate
product metadata is emitted to analytics.
"""

import json
import logging
from html import escape
from urllib.parse import urlencode
from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from pydantic import ValidationError

from app.bot.keyboards import main_menu_keyboard
from app.bot.persona_flow import SHARE_NAMESPACE
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.domain.horoscope import AstrologyReadingResult
from app.domain.reading_result import ReadingResult, ShareCardPayload
from app.providers.analytics import OracleProductEvent
from app.services.onboarding import OnboardingService, TelegramIdentity
from app.services.oracle_product_analytics import OracleProductAnalytics
from app.services.reading_history import ReadingHistoryService
from app.services.reading_service import ReadingService

logger = logging.getLogger(__name__)

router = Router(name="reading-share")

SHARE_FORMAT = "insight_card_v1"
SHARE_RENDERER_VERSION = "personal_share_v1"
SHARE_ENTRY_PAYLOAD = "share"
SHARE_PREVIEW_PREFIX = f"{SHARE_NAMESPACE}:preview:"
SHARE_CONFIRM_PREFIX = f"{SHARE_NAMESPACE}:confirm:"

SHARE_LANDING = (
    "✨ <b>Вам прислали инсайт из Numa</b>\n\n"
    "Здесь можно так же рассказать свою ситуацию обычными словами. Numa сама выберет, "
    "как лучше на неё посмотреть — Таро, отношения, рефлексия или астрология.\n\n"
    "Начните с того, что сейчас больше всего не даёт покоя."
)
SHARE_PREVIEW_INTRO = (
    "✨ <b>Карточка для друга</b>\n\n"
    "Ниже — именно тот текст, который можно отправить. Ваш вопрос, полный разбор и ссылка "
    "на вашу историю в него не добавляются.\n\n"
)
SHARE_READY = "Карточка готова. Нажмите «Выбрать чат» — Telegram откроет стандартное меню отправки."
SHARE_UNAVAILABLE = "Эта карточка сейчас недоступна. Откройте полный разбор из «Моих историй»."


@router.message(CommandStart(deep_link=True, magic=F.args == SHARE_ENTRY_PAYLOAD))
async def open_share_referral(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
) -> None:
    """Land a recipient on Numa without carrying any sender or reading identifier."""

    if message.from_user is None:
        return
    telegram_user = message.from_user
    user, _step = await onboarding.start(
        TelegramIdentity(
            telegram_user_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            language=telegram_user.language_code,
        )
    )
    # The dedicated payload makes the acquisition source observable in structured logs
    # without putting an inviter id, reading id or private content into the public link.
    logger.info(
        "share_referral_started subject_id=%s share_format=%s renderer_version=%s",
        user.id,
        SHARE_FORMAT,
        SHARE_RENDERER_VERSION,
    )
    await state.clear()
    await show_screen(
        message,
        Scene.MAIN_MENU,
        SHARE_LANDING,
        reply_markup=main_menu_keyboard(),
        state=state,
    )


@router.callback_query(F.data.startswith(SHARE_PREVIEW_PREFIX))
async def preview_reading_share(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    reading_history: ReadingHistoryService,
    reading_service: ReadingService,
    oracle_analytics: OracleProductAnalytics,
) -> None:
    """Show the exact public payload before the user is offered a share action."""

    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    reading_id = _reading_id(callback.data, SHARE_PREVIEW_PREFIX)
    user = await onboarding.current_user(callback.from_user.id)
    if reading_id is None or user is None:
        await callback.message.answer(SHARE_UNAVAILABLE)
        return
    card = await _owned_share_card(user.id, reading_id, reading_history, reading_service)
    if card is None:
        await callback.message.answer(SHARE_UNAVAILABLE)
        return
    await oracle_analytics.track(
        user.id,
        OracleProductEvent.SHARE_PREVIEWED,
        {
            "reading_id": reading_id,
            "share_format": SHARE_FORMAT,
            "renderer_version": SHARE_RENDERER_VERSION,
        },
    )
    await callback.message.answer(
        render_share_preview(card),
        reply_markup=share_preview_keyboard(reading_id),
    )


@router.callback_query(F.data.startswith(SHARE_CONFIRM_PREFIX))
async def confirm_reading_share(
    callback: CallbackQuery,
    bot: Bot,
    onboarding: OnboardingService,
    reading_history: ReadingHistoryService,
    reading_service: ReadingService,
    oracle_analytics: OracleProductAnalytics,
) -> None:
    """Record explicit share intent and hand off to Telegram's native share picker."""

    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    reading_id = _reading_id(callback.data, SHARE_CONFIRM_PREFIX)
    user = await onboarding.current_user(callback.from_user.id)
    if reading_id is None or user is None:
        await callback.message.answer(SHARE_UNAVAILABLE)
        return
    card = await _owned_share_card(user.id, reading_id, reading_history, reading_service)
    if card is None:
        await callback.message.answer(SHARE_UNAVAILABLE)
        return
    try:
        bot_user = await bot.get_me()
    except TelegramAPIError:
        await callback.message.answer("Не удалось открыть меню отправки. Попробуйте ещё раз.")
        return
    if not bot_user.username:
        await callback.message.answer("Не удалось открыть меню отправки. Попробуйте ещё раз.")
        return
    share_url = build_telegram_share_url(bot_user.username, card)
    await oracle_analytics.track(
        user.id,
        OracleProductEvent.SHARE_CONFIRMED,
        {
            "reading_id": reading_id,
            "share_format": SHARE_FORMAT,
            "renderer_version": SHARE_RENDERER_VERSION,
        },
    )
    await callback.message.answer(
        SHARE_READY,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📤 Выбрать чат", url=share_url)],
                [InlineKeyboardButton(text="← К моим историям", callback_data="menu:readings")],
            ]
        ),
    )


def share_preview_keyboard(reading_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Поделиться",
                    callback_data=f"{SHARE_CONFIRM_PREFIX}{reading_id}",
                )
            ],
            [InlineKeyboardButton(text="← К моим историям", callback_data="menu:readings")],
        ]
    )


def render_share_preview(card: ShareCardPayload) -> str:
    return (
        SHARE_PREVIEW_INTRO
        + f"<b>{escape(card.headline)}</b>\n\n"
        + escape(card.short_text)
        + "\n\n<i>Проверьте текст перед отправкой.</i>"
    )


def render_public_share(card: ShareCardPayload) -> str:
    """Render only the model's dedicated anonymous share payload plus product attribution."""

    return f"✨ {card.headline}\n\n{card.short_text}\n\n— Numa"


def build_telegram_share_url(bot_username: str, card: ShareCardPayload) -> str:
    """Create an aggregate-attributed referral URL with no reading or inviter id."""

    username = bot_username.removeprefix("@").strip()
    if not username:
        raise ValueError("bot username is required for sharing")
    referral = f"https://t.me/{username}?start={SHARE_ENTRY_PAYLOAD}"
    return "https://t.me/share/url?" + urlencode(
        {
            "url": referral,
            "text": render_public_share(card),
        }
    )


async def _owned_share_card(
    user_id: UUID,
    reading_id: UUID,
    history: ReadingHistoryService,
    readings: ReadingService,
) -> ShareCardPayload | None:
    if not await history.owns_full(user_id, reading_id):
        return None
    payload = await readings.load_result(reading_id, user_id)
    if payload is None:
        return None
    return _share_card_from_payload(payload)


def _share_card_from_payload(payload: dict[str, object]) -> ShareCardPayload | None:
    """Accept persisted JSON for both strict reading schemas without weakening validation."""

    encoded = json.dumps(payload, ensure_ascii=False)
    try:
        return ReadingResult.model_validate_json(encoded).share_card
    except ValidationError:
        pass
    try:
        return AstrologyReadingResult.model_validate_json(encoded).share_card
    except ValidationError:
        return None


def _reading_id(data: str | None, prefix: str) -> UUID | None:
    value = data or ""
    if not value.startswith(prefix):
        return None
    try:
        return UUID(value.removeprefix(prefix))
    except ValueError:
        return None
