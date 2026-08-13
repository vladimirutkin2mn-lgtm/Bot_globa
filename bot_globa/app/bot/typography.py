"""Rich text for Telegram, and the guarantee that it can never cost a message.

Markup carries meaning here — a heading is a heading, the disclaimer is set apart from
the reading it qualifies — so every outgoing message is parsed as HTML. That turns any
stray `<` or `&` in copy the bot did not write into a delivery failure rather than a
cosmetic glitch, which is the wrong trade for a product whose whole output is text.

Two things follow. Everything that did not originate in this repository is escaped at the
boundary where it is rendered, and a message Telegram refuses to parse is sent again
without markup. Ugly typography is acceptable; a lost reading is not.

The rules themselves are in `docs/telegram-ux-contract.md`.
"""

import logging
from html import escape
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import Response, TelegramMethod
from aiogram.methods.base import TelegramType

logger = logging.getLogger(__name__)

# Telegram phrases every markup failure this way, whatever the offending tag was.
_UNPARSEABLE = "can't parse entities"


def create_bot(token: str, session: BaseSession | None = None) -> Bot:
    """Build the bot every entry point shares: HTML copy with a plain-text safety net.

    Polling, the webhook API and three workers all talk to Telegram, and a formatting
    decision that lived in five constructors would drift between them within a release.
    """

    bot = Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    bot.session.middleware.register(PlainTextFallbackMiddleware())
    return bot


def quote(value: str) -> str:
    """Escape text the bot did not author so it can appear inside HTML copy.

    Applies to everything a user typed, everything a model wrote and everything a
    provider returned — a place name, a memory entry, a reading, a follow-up answer.
    """

    return escape(value, quote=False)


class PlainTextFallbackMiddleware(BaseRequestMiddleware):
    """Re-send a message Telegram refused to parse, this time without markup.

    Escaping is done at every boundary that renders untrusted text, so reaching this
    middleware means one of those boundaries was missed. The user still gets the message,
    and the log line says which method to go and look at.
    """

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as error:
            if _UNPARSEABLE not in str(error).lower() or not _carries_markup(method):
                raise
            logger.warning("telegram_markup_rejected method=%s", type(method).__name__)
            return await make_request(bot, _without_markup(method))


def _carries_markup(method: TelegramMethod[TelegramType]) -> bool:
    return "parse_mode" in type(method).model_fields


def _without_markup(method: TelegramMethod[TelegramType]) -> TelegramMethod[TelegramType]:
    update: dict[str, Any] = {"parse_mode": None}
    if "entities" in type(method).model_fields:
        update["entities"] = None
    if "caption_entities" in type(method).model_fields:
        update["caption_entities"] = None
    return method.model_copy(update=update)
