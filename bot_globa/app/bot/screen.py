"""One live screen per chat: navigation is edited in place, artifacts stay in the history.

A Telegram chat is not a feed. Everything that exists so the user can get somewhere — the
menu, a topic list, an intake prompt, a balance — belongs to a single message that follows
them, while the readings they came for stay behind as separate messages worth scrolling
back to. This module owns that split and the Telegram mechanics behind it: `show_screen`
moves the live screen, `send_artifact` adds something permanent and retires the pointer so
the next screen lands below the artifact instead of above it.

The rules, their failure modes and the invariants covered by tests are in
`docs/telegram-ux-contract.md`.
"""

import logging
from dataclasses import dataclass, replace
from typing import Any

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, Message

from app.bot.scene_media import (
    MEDIA_SCENES,
    TELEGRAM_CAPTION_LIMIT,
    Scene,
    answer_scene,
    edit_scene_photo,
    send_scene,
)

logger = logging.getLogger(__name__)

SCREEN_KEY = "pointer"

# The pointer lives in its own FSM record rather than in scenario data. Handlers reset a
# scenario with `state.clear()` all the time, and a pointer stored alongside the question
# and topic would vanish with them — leaving the next screen orphaned and stacking a
# duplicate on top of the live one. Separating the record makes that impossible instead
# of relying on every handler remembering a special reset helper.
SCREEN_DESTINY = "screen"


@dataclass(frozen=True, slots=True)
class ScreenPointer:
    """Where the live screen currently is, and in which form it can be edited."""

    message_id: int
    scene: Scene
    has_photo: bool

    def as_data(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "scene": self.scene.value,
            "has_photo": self.has_photo,
        }

    @classmethod
    def restore(cls, raw: Any) -> "ScreenPointer | None":
        """Rebuild a pointer written by an older release, or report that there is none.

        FSM data outlives deployments: a pointer whose shape or scene no longer exists is
        treated as absent, which costs one extra message instead of an unhandled error.
        """

        if not isinstance(raw, dict):
            return None
        try:
            return cls(
                message_id=int(raw["message_id"]),
                scene=Scene(str(raw["scene"])),
                has_photo=bool(raw["has_photo"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


async def show_screen(
    message: Message,
    scene: Scene,
    text: str,
    *,
    state: FSMContext,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Move the live screen to this scene, editing the existing message where possible.

    `message` only says which chat to draw in — it is the incoming update, which for a
    callback is whatever message carried the button. The pointer in FSM data is the only
    authority on which message *is* the screen, because buttons also live under artifacts
    and editing a finished reading would destroy what the user paid for.
    """

    bot = message.bot
    if bot is None:
        logger.warning("screen_without_bot scene=%s", scene.value)
        return
    chat_id = message.chat.id
    as_photo = scene in MEDIA_SCENES and len(text) <= TELEGRAM_CAPTION_LIMIT
    screen = _screen_state(state)
    pointer = ScreenPointer.restore((await screen.get_data()).get(SCREEN_KEY))
    if pointer is not None:
        # Telegram cannot turn a photo message into a text one or back, so a change of
        # form has to replace the message rather than edit it.
        if pointer.has_photo == as_photo and await _edit(
            bot, chat_id, pointer, scene, text, reply_markup
        ):
            await _store(state, ScreenPointer(pointer.message_id, scene, as_photo))
            return
        await _retire(bot, chat_id, pointer.message_id)
    sent = await send_scene(bot, chat_id, scene, text, reply_markup=reply_markup)
    await _store(state, ScreenPointer(sent.message_id, scene, bool(sent.photo)))


async def send_artifact(
    message: Message,
    scene: Scene,
    text: str,
    *,
    state: FSMContext,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Deliver something the user keeps, and let the next screen appear below it."""

    await answer_scene(message, scene, text, reply_markup=reply_markup)
    await forget_screen(state)


async def show_thinking(message: Message) -> None:
    """Say the bot is composing, so a generation that takes seconds is not read as a freeze.

    Telegram clears the indicator on its own after a few seconds or as soon as the next
    message arrives, so this is fire-and-forget: a chat action that fails changes nothing
    the user depends on.
    """

    bot = message.bot
    if bot is None:
        return
    try:
        await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    except TelegramAPIError:
        logger.info("chat_action_unavailable chat=%s", message.chat.id)


async def forget_screen(state: FSMContext) -> None:
    """Drop the pointer so the next screen is a fresh message at the bottom of the chat."""

    await _screen_state(state).update_data({SCREEN_KEY: None})


def _screen_state(state: FSMContext) -> FSMContext:
    """The sibling FSM record that holds the pointer for this chat."""

    return FSMContext(storage=state.storage, key=replace(state.key, destiny=SCREEN_DESTINY))


async def _edit(
    bot: Bot,
    chat_id: int,
    pointer: ScreenPointer,
    scene: Scene,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> bool:
    try:
        if not pointer.has_photo:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=pointer.message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return True
        if pointer.scene is not scene:
            return await edit_scene_photo(
                bot,
                chat_id,
                pointer.message_id,
                scene,
                text,
                reply_markup=reply_markup,
            )
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=pointer.message_id,
            caption=text,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as error:
        # Updates are delivered at least once, so the same screen is rendered twice more
        # often than it looks. Telegram reports the second render as an error; for the
        # user nothing is wrong, and sending a duplicate would be the actual defect.
        return "message is not modified" in str(error).lower()
    except TelegramAPIError:
        logger.warning("screen_edit_failed scene=%s", scene.value)
        return False
    return True


async def _retire(bot: Bot, chat_id: int, message_id: int) -> None:
    """Remove a screen that cannot be edited any more so no stale buttons stay behind.

    Only the bot's own screen is ever deleted. Telegram refuses to delete messages older
    than two days, and that refusal is expected rather than exceptional.
    """

    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramAPIError:
        logger.info("screen_retire_failed message_id=%s", message_id)


async def _store(state: FSMContext, pointer: ScreenPointer) -> None:
    await _screen_state(state).update_data({SCREEN_KEY: pointer.as_data()})
