"""Keep personal Numa flows out of Telegram group chats.

This router must be registered before personal routers. Group games use their own
callbacks and remain untouched; old personal buttons in a group are redirected to a
private chat without collecting personal data there.
"""

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import BaseFilter, Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import group_handlers

router = Router(name="chat_scope")
_GROUP_CHAT = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
_GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}

GROUP_ENTRY_TEXT = (
    "✨ <b>Numa в группе</b>\n\n"
    "Начните с 💞 /compatibility или ⚔️ /duel. Натальная карта не обязательна: "
    "если её нет, каждый участник сам выберет свой знак.\n\n"
    "Numa работает через команды и кнопки — читать обычную переписку для игр не нужно."
)

_PERSONAL_COMMANDS = (
    "tarot",
    "love",
    "psy",
    "astro",
    "settings",
    "birthprofile",
    "forgetme",
    "privacy",
    "subscribe",
    "unsub",
    "pay",
    "paysupport",
    "terms",
    "readings",
    "history",
)
_PERSONAL_CALLBACK_PREFIXES = (
    "menu:",
    "oracle:",
    "onboarding:",
    "tarot:",
    "love:",
    "psy:",
    "astro:",
    "memory:",
    "birth:",
    "profile:",
    "settings:",
    "credits:",
    "checkout:",
    "payment:",
    "subscription:",
    "refund:",
    "reading:",
    "readings:",
    "followup:",
    "history:",
    "story:",
    "stories:",
    "daily:",
    "horoscope:",
)
_PRACTICE_PAYLOADS = {"tarot", "love", "psy", "astro"}


def is_personal_callback_data(data: str | None) -> bool:
    """Return true only for callbacks that belong to private product surfaces."""

    return bool(data and data.startswith(_PERSONAL_CALLBACK_PREFIXES))


def private_payload_for_command(text: str | None) -> str | None:
    """Preserve an explicit practice when redirecting a command to private chat."""

    if not text:
        return None
    command = text.split(maxsplit=1)[0].lstrip("/").split("@", maxsplit=1)[0].lower()
    return command if command in _PRACTICE_PAYLOADS else None


def private_payload_for_callback(data: str | None) -> str | None:
    """Preserve an explicit practice when an old group button is pressed."""

    if not data:
        return None
    prefix = data.split(":", maxsplit=1)[0]
    if prefix in _PRACTICE_PAYLOADS:
        return prefix
    if data.startswith("menu:"):
        target = data.split(":", maxsplit=1)[1]
        if target in _PRACTICE_PAYLOADS:
            return target
    return None


async def _private_keyboard(bot: Bot, payload: str | None) -> InlineKeyboardMarkup | None:
    me = await bot.get_me()
    if not me.username:
        return None
    username = me.username.removeprefix("@")
    url = f"https://t.me/{username}"
    if payload is not None:
        url = f"{url}?start={payload}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть Numa в личке", url=url)]]
    )


class GroupPersonalCallbackFilter(BaseFilter):
    """Match private callbacks only when they are pressed from a group message."""

    async def __call__(self, callback: CallbackQuery) -> bool:
        message = callback.message
        return (
            isinstance(message, Message)
            and message.chat.type in _GROUP_TYPES
            and is_personal_callback_data(callback.data)
        )


@router.message(CommandStart(), _GROUP_CHAT)
async def group_start(message: Message) -> None:
    """Treat every group /start payload as group entry, including startgroup=party."""

    await message.answer(GROUP_ENTRY_TEXT, reply_markup=group_handlers._party_menu_keyboard())


@router.message(Command(*_PERSONAL_COMMANDS), _GROUP_CHAT)
async def personal_command_in_group(message: Message, bot: Bot) -> None:
    """Never begin a personal command flow in a group chat."""

    await message.answer(
        "Личные разборы, профиль и оплаты доступны только в личном чате с Numa.",
        reply_markup=await _private_keyboard(bot, private_payload_for_command(message.text)),
    )


@router.callback_query(GroupPersonalCallbackFilter())
async def personal_callback_in_group(callback: CallbackQuery, bot: Bot) -> None:
    """Redirect legacy personal buttons without invoking their private handlers."""

    await callback.answer("Личный сценарий откроется в личном чате с Numa.")
    if not isinstance(callback.message, Message):
        return
    await callback.message.answer(
        "Этот сценарий личный. Продолжить его можно один на один с Numa.",
        reply_markup=await _private_keyboard(bot, private_payload_for_callback(callback.data)),
    )
