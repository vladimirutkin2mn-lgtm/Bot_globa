"""The commands Telegram itself offers, and the deep links that skip the menu.

Two pieces of chrome the bot owns rather than draws. `set_my_commands` is what makes the
blue Menu button in the Telegram composer useful instead of empty, and a `?start=` payload
lets an ad or a shared link land on the scenario it promised rather than on a menu the
reader then has to re-navigate.

A payload is a scenario code and nothing else. It arrives from outside, so it selects a
handler by exact match against a router's own namespace and is never interpolated,
executed or stored.
"""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, MenuButtonCommands

from app.bot.group_compatibility_handlers import install_group_compatibility_mechanics
from app.bot.group_compatibility_ux import install_group_compatibility_ux
from app.bot.group_social_handlers import install_group_social_mechanics

logger = logging.getLogger(__name__)

BOT_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand(command="start", description="🔮 Начать заново"),
    BotCommand(command="love", description="💞 Любовный оракул"),
    BotCommand(command="tarot", description="🔮 Таролог"),
    BotCommand(command="psy", description="🌙 Мистический психолог"),
    BotCommand(command="astro", description="🪐 Астролог"),
    BotCommand(command="pay", description="💳 Оплата"),
    BotCommand(command="paysupport", description="💬 Помощь с оплатой"),
)

GROUP_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand(command="card", description="🔮 Карта дня для всего чата"),
    BotCommand(command="compatibility", description="💞 Совместимость участников"),
    BotCommand(command="party", description="🎉 Игры для компании"),
    BotCommand(command="event", description="🃏 Расклад на событие"),
    BotCommand(command="chat", description="🎭 Архетип этого чата"),
    BotCommand(command="grouphelp", description="✨ Игры Numa для группы"),
)

install_group_social_mechanics()
install_group_compatibility_mechanics()
install_group_compatibility_ux()


async def configure_commands(bot: Bot) -> None:
    """Publish private defaults plus a deliberately tiny command menu for groups.

    Group commands override the default command list only inside group chats, so payment,
    support and personal-reading commands do not become noisy group affordances. Startup
    must not depend on Telegram being reachable: a cosmetic call may never cause outage.

    Compatibility no longer relies on replying to another member's message. Telegram
    Group Privacy Mode does not reliably deliver that shape, so the command opens a lobby
    and every subsequent selection is done with callbacks that are explicitly addressed
    to Numa.
    """

    try:
        await bot.set_my_commands(list(BOT_COMMANDS))
        await bot.set_my_commands(
            list(GROUP_COMMANDS),
            scope=BotCommandScopeAllGroupChats(),
        )
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except TelegramAPIError:
        logger.warning("bot_commands_not_published")
