"""Remove overlapping daily group rituals from the public Numa experience."""

from collections.abc import Callable
from datetime import date

from aiogram import Bot, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import group_handlers, group_social_handlers, group_viral_handlers
from app.bot.scene_media import send_art
from app.bot.tarot_art import card_art

_GROUP_CHAT = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
_INSTALL_MARKERS: set[str] = set()
_PREVIOUS_PARTY_MENU: Callable[[], InlineKeyboardMarkup] | None = None


def _clean_party_menu() -> InlineKeyboardMarkup:
    if _PREVIOUS_PARTY_MENU is None:
        raise RuntimeError("group daily cleanup is not installed")
    source = _PREVIOUS_PARTY_MENU()
    rows: list[list[InlineKeyboardButton]] = []
    for row in source.inline_keyboard:
        cleaned: list[InlineKeyboardButton] = []
        for button in row:
            if button.callback_data == "social:party:evening":
                continue
            if button.callback_data == "group:party:vibe":
                cleaned.append(
                    InlineKeyboardButton(
                        text="🔥 Вайб вечера",
                        callback_data="group:party:vibe",
                    )
                )
                continue
            cleaned.append(button)
        if cleaned:
            rows.append(cleaned)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_party_vibe(
    message: Message,
    bot: Bot,
    *,
    for_date: date,
    back_to_party: bool = False,
) -> None:
    result = group_handlers.party_vibe_for_day(message.chat.id, for_date)
    text = (
        "🔥 Вайб этого вечера\n\n"
        f"{result.title}\n"
        f"{result.text}\n\n"
        "Вопрос только в том, кто первым это запустит 👀"
    )
    username = await group_handlers._bot_username(bot)
    keyboard = (
        group_handlers._private_keyboard(
            username,
            persona="tarot",
            label="🔮 Что ждёт лично меня?",
        )
        if username
        else None
    )
    if back_to_party:
        keyboard = group_handlers._append_back(
            keyboard,
            text="← К играм",
            callback_data="group:party:menu",
        )
    await send_art(
        bot,
        message.chat.id,
        card_art(result.card.code),
        text,
        reply_markup=keyboard,
    )


async def group_cosmic_weather(message: Message) -> None:
    advice = group_viral_handlers.cosmic_advice_for_day(message.date.date())
    mercury_motion = "ретроградный" if advice.mercury_retrograde else "прямой"
    await message.answer(
        "🪐 <b>Космическая погода</b>\n\n"
        f"☿ Меркурий — {advice.mercury_sign}, {mercury_motion}\n"
        f"☾ Луна — {advice.moon_sign}\n\n"
        f"{advice.text}\n\n"
        "<em>Текущий астрологический фон дня.</em>"
    )


def _clean_help(text: str) -> str:
    return (
        text.replace("🎭 /chat — архетип этого чата\n", "")
        .replace("🔮 /forecast — что ждёт чат сегодня\n", "")
        .replace(
            "🪐 /advice — космический совет дня\n",
            "🪐 /advice — космическая погода\n",
        )
    )


def install_group_daily_cleanup() -> None:
    """Expose four distinct daily concepts instead of overlapping forecasts."""

    global _PREVIOUS_PARTY_MENU
    if "group_daily_cleanup" in _INSTALL_MARKERS:
        return

    router = group_handlers.router
    removed = {
        group_handlers.group_chat_archetype,
        group_social_handlers.group_forecast,
        group_viral_handlers.group_advice,
    }
    router.message.handlers[:] = [
        handler for handler in router.message.handlers if handler.callback not in removed
    ]
    router.message(_GROUP_CHAT, Command("advice"))(group_cosmic_weather)

    _PREVIOUS_PARTY_MENU = group_handlers._party_menu_keyboard
    group_handlers._party_menu_keyboard = _clean_party_menu
    group_handlers._send_party_vibe = _send_party_vibe
    group_handlers.GROUP_HELP = _clean_help(group_handlers.GROUP_HELP)
    _INSTALL_MARKERS.add("group_daily_cleanup")
