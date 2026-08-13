"""The live screen moves in place; artifacts stay where the user can find them."""

from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (
    DeleteMessage,
    EditMessageCaption,
    EditMessageMedia,
    EditMessageText,
    SendMessage,
    TelegramMethod,
)
from aiogram.methods.base import TelegramType
from aiogram.types import Chat, Message
from aiogram.types import User as TelegramUser

from app.bot import scene_media
from app.bot.scene_media import MEDIA_SCENES, Scene
from app.bot.screen import forget_screen, send_artifact, show_screen
from tests.telegram_doubles import sent

CHAT_ID = 42

# A scene whose copy is decoration-free, so a screen made of it is a text message.
TEXT_SCENE = Scene.MAIN_MENU
# A scene the CJM illustrates, so a screen made of it is a photo with a caption.
PHOTO_SCENE = Scene.TAROT_ENTRY


class RecordingSession(AiohttpSession):
    def __init__(self) -> None:
        super().__init__()
        self.methods: list[TelegramMethod[Any]] = []
        self.refuse_edits: Exception | None = None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,  # noqa: ASYNC109 -- aiogram session contract
    ) -> TelegramType:
        self.methods.append(method)
        if self.refuse_edits is not None and isinstance(
            method, EditMessageText | EditMessageCaption | EditMessageMedia
        ):
            raise self.refuse_edits
        reply = sent(method, len(self.methods) + 100)
        return cast("TelegramType", reply if reply is not None else True)

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109 -- aiogram session contract
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        if False:  # pragma: no cover - required async-generator shape
            yield b""


@pytest.fixture(autouse=True)
def _clean_file_id_cache() -> Iterator[None]:
    scene_media._telegram_file_ids.clear()
    yield
    scene_media._telegram_file_ids.clear()


@pytest.fixture
async def chat() -> AsyncGenerator[tuple[Message, FSMContext, RecordingSession], None]:
    session = RecordingSession()
    bot = Bot("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session)
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=CHAT_ID, type="private"),
        from_user=TelegramUser(id=CHAT_ID, is_bot=False, first_name="Анна"),
        text="кнопка",
    ).as_(bot)
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=bot.id, chat_id=CHAT_ID, user_id=CHAT_ID))
    yield message, state, session
    await bot.session.close()


def _kinds(session: RecordingSession) -> list[str]:
    return [type(method).__name__ for method in session.methods]


def _not_modified() -> TelegramBadRequest:
    return TelegramBadRequest(
        method=EditMessageText(chat_id=CHAT_ID, message_id=1, text="x"),
        message="Bad Request: message is not modified",
    )


def _too_old() -> TelegramBadRequest:
    return TelegramBadRequest(
        method=EditMessageText(chat_id=CHAT_ID, message_id=1, text="x"),
        message="Bad Request: message can't be edited",
    )


async def test_the_scenes_a_screen_can_illustrate_are_the_ones_the_cjm_illustrates() -> None:
    assert PHOTO_SCENE in MEDIA_SCENES
    assert TEXT_SCENE not in MEDIA_SCENES


async def test_the_second_screen_edits_the_first_instead_of_sending_again(
    chat: tuple[Message, FSMContext, RecordingSession],
) -> None:
    message, state, session = chat

    await show_screen(message, TEXT_SCENE, "Главное меню", state=state)
    await show_screen(message, Scene.PRIVACY, "Приватность", state=state)

    assert _kinds(session) == ["SendMessage", "EditMessageText"]
    edited = session.methods[-1]
    assert isinstance(edited, EditMessageText)
    assert edited.message_id == 101
    assert edited.text == "Приватность"


async def test_a_photo_screen_swaps_its_illustration_rather_than_the_whole_message(
    chat: tuple[Message, FSMContext, RecordingSession],
) -> None:
    message, state, session = chat

    await show_screen(message, PHOTO_SCENE, "Таролог", state=state)
    await show_screen(message, Scene.GENERATING, "Собираю разбор", state=state)

    assert _kinds(session) == ["SendPhoto", "EditMessageMedia"]


async def test_the_same_photo_scene_only_rewrites_its_caption(
    chat: tuple[Message, FSMContext, RecordingSession],
) -> None:
    message, state, session = chat

    await show_screen(message, PHOTO_SCENE, "Таролог", state=state)
    await show_screen(message, PHOTO_SCENE, "Эта тема недоступна.", state=state)

    assert _kinds(session) == ["SendPhoto", "EditMessageCaption"]


async def test_changing_form_replaces_the_screen_because_telegram_cannot_edit_across_it(
    chat: tuple[Message, FSMContext, RecordingSession],
) -> None:
    message, state, session = chat

    await show_screen(message, PHOTO_SCENE, "Таролог", state=state)
    await show_screen(message, TEXT_SCENE, "Главное меню", state=state)

    assert _kinds(session) == ["SendPhoto", "DeleteMessage", "SendMessage"]
    retired = session.methods[1]
    assert isinstance(retired, DeleteMessage)
    assert retired.message_id == 101


async def test_re_rendering_the_same_screen_is_not_an_error_and_sends_nothing(
    chat: tuple[Message, FSMContext, RecordingSession],
) -> None:
    """At-least-once delivery renders the same screen twice; a duplicate would be the bug."""

    message, state, session = chat
    await show_screen(message, TEXT_SCENE, "Главное меню", state=state)
    session.refuse_edits = _not_modified()

    await show_screen(message, TEXT_SCENE, "Главное меню", state=state)

    assert _kinds(session) == ["SendMessage", "EditMessageText"]


async def test_a_screen_that_can_no_longer_be_edited_is_retired_and_sent_again(
    chat: tuple[Message, FSMContext, RecordingSession],
) -> None:
    message, state, session = chat
    await show_screen(message, TEXT_SCENE, "Главное меню", state=state)
    session.refuse_edits = _too_old()

    await show_screen(message, Scene.PRIVACY, "Приватность", state=state)

    assert _kinds(session) == ["SendMessage", "EditMessageText", "DeleteMessage", "SendMessage"]
    assert isinstance(session.methods[-1], SendMessage)


async def test_an_artifact_is_sent_and_the_next_screen_lands_below_it(
    chat: tuple[Message, FSMContext, RecordingSession],
) -> None:
    message, state, session = chat
    await show_screen(message, TEXT_SCENE, "Главное меню", state=state)

    await send_artifact(message, Scene.FULL_READING, "Полный разбор", state=state)
    await show_screen(message, TEXT_SCENE, "Главное меню", state=state)

    assert _kinds(session) == ["SendMessage", "SendPhoto", "SendMessage"]


async def test_clearing_the_scenario_never_loses_the_live_screen(
    chat: tuple[Message, FSMContext, RecordingSession],
) -> None:
    """A reset erases the question and the topic; the screen is not part of that."""

    message, state, session = chat
    await show_screen(message, TEXT_SCENE, "Главное меню", state=state)
    await state.update_data(topic="decision")

    await state.clear()
    await show_screen(message, Scene.PRIVACY, "Приватность", state=state)

    assert await state.get_data() == {}
    assert _kinds(session) == ["SendMessage", "EditMessageText"]


async def test_forgetting_the_screen_starts_a_new_one(
    chat: tuple[Message, FSMContext, RecordingSession],
) -> None:
    message, state, session = chat
    await show_screen(message, TEXT_SCENE, "Главное меню", state=state)

    await forget_screen(state)
    await show_screen(message, TEXT_SCENE, "Главное меню", state=state)

    assert _kinds(session) == ["SendMessage", "SendMessage"]


async def test_copy_too_long_for_a_caption_becomes_a_text_screen_that_stays_editable(
    chat: tuple[Message, FSMContext, RecordingSession],
) -> None:
    message, state, session = chat
    long_copy = "д" * (scene_media.TELEGRAM_CAPTION_LIMIT + 1)

    await show_screen(message, PHOTO_SCENE, long_copy, state=state)
    await show_screen(message, PHOTO_SCENE, "Короткая подпись", state=state)

    # The first screen could not be a caption, so it was text; the second fits a caption,
    # which is a change of form and therefore a replacement rather than an edit.
    assert _kinds(session) == ["SendMessage", "DeleteMessage", "SendPhoto"]
