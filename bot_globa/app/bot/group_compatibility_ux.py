"""Privacy-safe interactive UX for group compatibility.

Telegram privacy mode does not reliably deliver a plain command that replies to another
member's message. Selection therefore happens entirely through callbacks after the first
entry point: people explicitly join the pair themselves, which is also their consent to
use a saved astro profile for this one group result.
"""

from html import escape

from aiogram import Bot, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import group_compatibility_handlers as compatibility
from app.bot import group_handlers
from app.bot import group_social_handlers as social

_GROUP_CHAT = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
_GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}
_INSTALL_MARKERS: set[str] = set()


def _lobby_keyboard(inviter_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💞 Я + другой",
                    callback_data=f"gcu:m:{inviter_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Два других",
                    callback_data=f"gcu:o:{inviter_id}",
                )
            ],
        ]
    )


def _join_self_keyboard(inviter_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✨ Я второй",
                    callback_data=f"gcu:j:{inviter_id}",
                )
            ]
        ]
    )


def _join_first_keyboard(inviter_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="1️⃣ Я первый",
                    callback_data=f"gcu:f:{inviter_id}",
                )
            ]
        ]
    )


def _join_second_keyboard(inviter_id: int, first_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="2️⃣ Я второй",
                    callback_data=f"gcu:s:{inviter_id}:{first_id}",
                )
            ]
        ]
    )


def _party_menu_with_compatibility() -> InlineKeyboardMarkup:
    current = social._social_party_menu_keyboard()
    rows = [
        [InlineKeyboardButton(text="💞 Совместимость", callback_data="gcu:open")],
        *[list(row) for row in current.inline_keyboard],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def compatibility_entry_ux(message: Message) -> None:
    """Open a callback-only lobby; replying to another member is no longer required."""

    author = message.from_user
    if author is None:
        return
    await message.answer(
        "💞 <b>Совместимость</b>\n\n"
        "Кого сравниваем?\n\n"
        "Никаких reply-команд: участники сами подтверждают участие кнопкой.",
        reply_markup=_lobby_keyboard(author.id),
    )


async def compatibility_lobby_action(callback: CallbackQuery, bot: Bot) -> None:
    message = callback.message
    data = callback.data
    if not isinstance(message, Message) or message.chat.type not in _GROUP_TYPES or data is None:
        await callback.answer()
        return

    if data == "gcu:open":
        await callback.answer()
        await message.edit_text(
            "💞 <b>Совместимость</b>\n\nКого сравниваем?",
            reply_markup=_lobby_keyboard(callback.from_user.id),
        )
        return

    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "gcu":
        await callback.answer()
        return

    action = parts[1]
    try:
        inviter_id = int(parts[2])
    except ValueError:
        await callback.answer("Не получилось открыть совместимость.")
        return

    if action in {"m", "o"} and callback.from_user.id != inviter_id:
        await callback.answer("Режим выбирает тот, кто запустил совместимость.")
        return

    if action == "m" and len(parts) == 3:
        inviter_name = callback.from_user.full_name
        await callback.answer()
        await message.edit_text(
            f"💞 <b>{escape(inviter_name)}</b> уже в паре.\n\n"
            "Второй участник — нажми «Я второй».\n\n"
            "Нажатие означает согласие использовать сохранённый астропрофиль "
            "только для этого результата в группе.",
            reply_markup=_join_self_keyboard(inviter_id),
        )
        return

    if action == "o" and len(parts) == 3:
        await callback.answer()
        await message.edit_text(
            "👥 <b>Сравним двух других людей</b>\n\n"
            "Первый участник — нажми «Я первый».\n\n"
            "Нажатие означает согласие использовать сохранённый астропрофиль "
            "только для этого результата в группе.",
            reply_markup=_join_first_keyboard(inviter_id),
        )
        return

    if action == "j" and len(parts) == 3:
        second_id = callback.from_user.id
        if second_id == inviter_id:
            await callback.answer("Нужен ещё один человек 🙂")
            return
        first_name = await compatibility._member_name(bot, message, inviter_id)
        second_name = callback.from_user.full_name
        await callback.answer("Пара собрана ✨")
        await message.edit_text(
            f"💞 <b>{escape(first_name)} × {escape(second_name)}</b>\n\nЧто именно смотрим?",
            reply_markup=compatibility._context_keyboard(inviter_id, inviter_id, second_id),
        )
        return

    if action == "f" and len(parts) == 3:
        first_id = callback.from_user.id
        if first_id == inviter_id:
            await callback.answer("Здесь нужны два других участника 🙂")
            return
        first_name = callback.from_user.full_name
        await callback.answer("Первый участник выбран ✨")
        await message.edit_text(
            f"👥 Первый — <b>{escape(first_name)}</b>.\n\n"
            "Теперь второй участник — нажми «Я второй».\n\n"
            "Нажатие означает согласие использовать сохранённый астропрофиль "
            "только для этого результата в группе.",
            reply_markup=_join_second_keyboard(inviter_id, first_id),
        )
        return

    if action == "s" and len(parts) == 4:
        try:
            first_id = int(parts[3])
        except ValueError:
            await callback.answer("Не получилось выбрать второго участника.")
            return
        second_id = callback.from_user.id
        if second_id in {inviter_id, first_id}:
            await callback.answer("Нужен другой участник 🙂")
            return
        first_name = await compatibility._member_name(bot, message, first_id)
        second_name = callback.from_user.full_name
        await callback.answer("Пара собрана ✨")
        await message.edit_text(
            f"💞 <b>{escape(first_name)} × {escape(second_name)}</b>\n\nЧто именно смотрим?",
            reply_markup=compatibility._context_keyboard(inviter_id, first_id, second_id),
        )
        return

    await callback.answer()


def install_group_compatibility_ux() -> None:
    """Replace reply-based person selection with a callback-only lobby."""

    if "group_compatibility_ux" in _INSTALL_MARKERS:
        return
    router = group_handlers.router
    router.message.handlers[:] = [
        handler
        for handler in router.message.handlers
        if handler.callback
        not in {
            compatibility.compatibility_entry,
            compatibility.compatibility_second,
            compatibility_entry_ux,
        }
    ]
    router.message(_GROUP_CHAT, Command("compatibility"))(compatibility_entry_ux)
    router.callback_query(F.data.startswith("gcu:"))(compatibility_lobby_action)
    group_handlers._party_menu_keyboard = _party_menu_with_compatibility
    _INSTALL_MARKERS.add("group_compatibility_ux")
