"""The wait becomes the reveal of a spread already drawn, and never invents one."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageMedia, SendPhoto, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import Chat, Message
from aiogram.types import User as TelegramUser
from aiogram.types.input_file import FSInputFile

from app.bot import scene_media
from app.bot.persona_flow import PersonaReadingBundle
from app.bot.persona_flows import TAROT_FLOW
from app.bot.persona_handlers import PersonaReadingHandlers
from app.bot.reading_renderer import (
    REVEAL_CLOSING,
    render_reveal,
    reveal_progress,
)
from app.bot.tarot_art import card_art
from app.domain.reading_generation import ReadingSymbolContext
from app.services.monetized_reading import MonetizedReadingService
from app.services.oracle_memory import OracleMemoryService
from app.services.persona_reading import PersonaReadingUseCase
from app.services.symbolic_engine import TarotSymbolDrawer
from tests.telegram_doubles import sent, shown_texts

READING_ID = UUID("11111111-2222-3333-4444-555555555555")
USER_ID = UUID("99999999-8888-7777-6666-555555555555")
CHAT_ID = 42
# The reveal is exercised against a drawer pinned to one layout, because the layout a
# reading actually uses is frozen on the Reading rather than chosen at draw time.
SPREAD_CODE = "three_card_v1"


def _drawer() -> TarotSymbolDrawer:
    return TarotSymbolDrawer(spread_code=SPREAD_CODE)


def _spread() -> tuple[ReadingSymbolContext, ...]:
    return _drawer().draw(READING_ID)


def test_the_bar_counts_only_what_has_been_turned_over() -> None:
    assert reveal_progress(0, 3) == "▱▱▱"
    assert reveal_progress(2, 3) == "▰▰▱"
    assert reveal_progress(3, 3) == "▰▰▰"


def test_the_bar_refuses_to_claim_more_than_the_spread_holds() -> None:
    """A progress indicator that can overstate is the one thing this product must not ship."""

    with pytest.raises(ValueError):
        reveal_progress(4, 3)


def test_each_step_shows_exactly_the_symbols_revealed_so_far() -> None:
    symbols = _drawer().draw(READING_ID)

    first = render_reveal(TAROT_FLOW.copy, symbols, 1)
    second = render_reveal(TAROT_FLOW.copy, symbols, 2)

    assert symbols[0].display_name in first
    assert symbols[1].display_name not in first
    assert symbols[0].display_name in second and symbols[1].display_name in second
    assert reveal_progress(1, len(symbols)) in first
    assert REVEAL_CLOSING in first


def test_the_revealed_spread_is_the_one_the_reading_will_explain() -> None:
    """The draw is seeded from `reading_id`, so the ritual cannot drift from the result."""

    first = render_reveal(TAROT_FLOW.copy, _drawer().draw(READING_ID), 3)
    again = render_reveal(TAROT_FLOW.copy, _drawer().draw(READING_ID), 3)

    assert first == again


def test_revealing_nothing_is_a_programming_error_not_an_empty_screen() -> None:
    with pytest.raises(ValueError):
        render_reveal(TAROT_FLOW.copy, _spread(), 0)


class RecordingSession(AiohttpSession):
    def __init__(self) -> None:
        super().__init__()
        self.methods: list[TelegramMethod[Any]] = []

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,  # noqa: ASYNC109 -- aiogram session contract
    ) -> TelegramType:
        self.methods.append(method)
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


class SlowUseCase:
    """A use case whose interpretation only finishes once the test allows it."""

    def __init__(self) -> None:
        self.finish = asyncio.Event()
        self.edits_before_result = -1

    async def draw_symbols(
        self, reading_id: UUID, user_id: UUID
    ) -> tuple[ReadingSymbolContext, ...]:
        return _drawer().draw(reading_id)

    async def generate_existing_preview(self, reading_id: UUID, user_id: UUID) -> object:
        await self.finish.wait()
        return object()


@pytest.fixture
async def revealing() -> AsyncGenerator[
    tuple[PersonaReadingHandlers, Message, FSMContext, RecordingSession, SlowUseCase], None
]:
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
    use_case = SlowUseCase()
    yield PersonaReadingHandlers(TAROT_FLOW), message, state, session, use_case
    await bot.session.close()


def _bundle(use_case: SlowUseCase) -> PersonaReadingBundle:
    return PersonaReadingBundle(
        use_case=cast("PersonaReadingUseCase", use_case),
        monetized=cast("MonetizedReadingService", object()),
        full_price_label="199 ₽",
        memory=cast("OracleMemoryService", object()),
        reveal_seconds=0.0,
    )


async def test_the_spread_is_revealed_while_the_interpretation_is_still_being_written(
    revealing: tuple[PersonaReadingHandlers, Message, FSMContext, RecordingSession, SlowUseCase],
) -> None:
    """The ritual has to fill the wait, not be added to it."""

    handlers, message, state, session, use_case = revealing
    bundle = _bundle(use_case)
    generation = asyncio.ensure_future(use_case.generate_existing_preview(READING_ID, READING_ID))

    await handlers._reveal_spread(message, state, READING_ID, bundle, USER_ID)
    revealed_while_pending = not generation.done()
    use_case.finish.set()
    await generation

    assert revealed_while_pending
    symbols = _drawer().draw(READING_ID)
    shown = shown_texts(session.methods)
    # One message for the whole reveal: the first card opens a photo screen and each
    # later card replaces its picture, so nothing accumulates in the chat.
    assert len(session.methods) == len(symbols)
    assert shown == [
        render_reveal(TAROT_FLOW.copy, symbols, revealed) for revealed in range(1, len(symbols) + 1)
    ]


async def test_a_persona_without_symbols_simply_waits(
    revealing: tuple[PersonaReadingHandlers, Message, FSMContext, RecordingSession, SlowUseCase],
) -> None:
    handlers, message, state, session, _ = revealing

    class Wordy(SlowUseCase):
        async def draw_symbols(
            self, reading_id: UUID, user_id: UUID
        ) -> tuple[ReadingSymbolContext, ...]:
            return ()

    await handlers._reveal_spread(message, state, READING_ID, _bundle(Wordy()), USER_ID)

    assert session.methods == []


async def test_each_step_turns_over_the_card_that_was_drawn(
    revealing: tuple[PersonaReadingHandlers, Message, FSMContext, RecordingSession, SlowUseCase],
) -> None:
    """The picture has to be the exact card the deterministic engine selected."""

    handlers, message, state, session, use_case = revealing
    scene_media._telegram_file_ids.clear()

    await handlers._reveal_spread(message, state, READING_ID, _bundle(use_case), USER_ID)

    symbols = _drawer().draw(READING_ID)
    # The first card arrives as a new photo screen; every later one swaps the media,
    # because a different card is a different picture rather than a new caption.
    assert [type(method).__name__ for method in session.methods] == [
        "SendPhoto",
        *["EditMessageMedia"] * (len(symbols) - 1),
    ]
    assert _photo_names(session) == [
        _expected_art_name(context.symbol.symbol_id) for context in symbols
    ]


def _source_name(photo: str | FSInputFile) -> str:
    if isinstance(photo, FSInputFile):
        return photo.filename or ""
    return photo


def _expected_art_name(symbol_id: str) -> str:
    art = card_art(symbol_id)
    assert art is not None
    return art.path.name


def _photo_names(session: RecordingSession) -> list[str]:
    names: list[str] = []
    for method in session.methods:
        if isinstance(method, EditMessageMedia):
            photo = method.media.media
        else:
            assert isinstance(method, SendPhoto)
            photo = method.photo
        assert isinstance(photo, (str, FSInputFile))
        names.append(_source_name(photo))
    return names
