"""UX layer for selecting one or two people in group compatibility.

Telegram's group command picker is the reliable affordance we already expose. Reuse the
same `/compatibility` command for both selections instead of teaching users a hidden
second command.
"""

from html import escape

from aiogram import Bot, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import group_compatibility_handlers as compatibility
from app.bot import group_handlers

_GROUP_CHAT = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
_INSTALL_MARKERS: set[str] = set()
_ORIGINAL_PAIR_CHOICE = compatibility._handle_pair_choice


async def compatibility_entry_ux(message: Message) -> None:
    """Start compatibility with an explicit, menu-oriented instruction."""

    author = message.from_user
    replied = message.reply_to_message
    selected = replied.from_user if replied is not None else None
    if author is None:
        return
    if selected is None or selected.is_bot or selected.id == author.id:
        await message.answer(
            "💞 Чтобы выбрать человека:\n\n"
            "1. Ответьте на его сообщение.\n"
            "2. Откройте меню Numa и выберите «💞 Совместимость».\n\n"
            "После этого можно сравнить его с собой или выбрать второго человека."
        )
        return
    await compatibility.compatibility_entry(message)


async def compatibility_second_ux(message: Message, bot: Bot, state: FSMContext) -> None:
    """Use `/compatibility` again while the inviter is choosing the second person."""

    author = message.from_user
    replied = message.reply_to_message
    second = replied.from_user if replied is not None else None
    data = await state.get_data()
    first_id = data.get("compatibility_first_id")
    first_name = data.get("compatibility_first_name")
    if author is None or not isinstance(first_id, int) or not isinstance(first_name, str):
        await state.clear()
        return
    if second is None or second.is_bot or second.id in {author.id, first_id}:
        await message.answer(
            "👥 Теперь выберите второго человека:\n\n"
            "1. Ответьте на его сообщение.\n"
            "2. Снова выберите «💞 Совместимость» в меню Numa."
        )
        return
    await compatibility.compatibility_second(message, bot, state)


async def _handle_pair_choice_ux(
    callback: CallbackQuery,
    message: Message,
    bot: Bot,
    state: FSMContext,
    *,
    inviter_id: int,
    selected_id: int,
    choose_other: bool,
) -> None:
    """Keep existing self-pair logic; clarify and simplify the two-person branch."""

    if not choose_other:
        await _ORIGINAL_PAIR_CHOICE(
            callback,
            message,
            bot,
            state,
            inviter_id=inviter_id,
            selected_id=selected_id,
            choose_other=False,
        )
        return
    if callback.from_user.id != inviter_id:
        await callback.answer("Пару выбирает тот, кто запустил сценарий.")
        return
    selected_name = await compatibility._member_name(bot, message, selected_id)
    await state.set_state(compatibility.GroupCompatibilityStates.waiting_for_second)
    await state.set_data(
        {
            "compatibility_first_id": selected_id,
            "compatibility_first_name": selected_name,
        }
    )
    await callback.answer()
    await message.edit_text(
        f"👥 Первый — {escape(selected_name)}.\n\n"
        "Теперь ответьте на сообщение второго человека и снова выберите "
        "«💞 Совместимость» в меню Numa."
    )


def install_group_compatibility_ux() -> None:
    """Replace the hidden `/with` step with the same visible compatibility command."""

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
            compatibility_second_ux,
        }
    ]
    compatibility._handle_pair_choice = _handle_pair_choice_ux
    router.message(
        _GROUP_CHAT,
        compatibility.GroupCompatibilityStates.waiting_for_second,
        Command("compatibility"),
    )(compatibility_second_ux)
    router.message(_GROUP_CHAT, Command("compatibility"))(compatibility_entry_ux)
    _INSTALL_MARKERS.add("group_compatibility_ux")
