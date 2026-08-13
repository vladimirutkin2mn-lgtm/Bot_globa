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
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import Chat, Message
from aiogram.types import User as TelegramUser

from app.bot.persona_flow import PersonaReadingBundle
from app.bot.persona_flows import TAROT_FLOW
from app.bot.persona_handlers import PersonaReadingHandlers
from app.bot.reading_renderer import (
    REVEAL_CLOSING,
    render_reveal,
    reveal_progress,
)
from app.domain.reading_generation import ReadingSymbolContext
from app.services.monetized_reading import MonetizedReadingService
from app.services.oracle_memory import OracleMemoryService
from app.services.persona_reading import PersonaReadingUseCase
from app.services.symbolic_engine import TarotSymbolDrawer
from tests.telegram_doubles import sent, shown_texts

READING_ID = UUID("11111111-2222-3333-4444-555555555555")
CHAT_ID = 42


def _spread() -> tuple[ReadingSymbolContext, ...]:
    return TarotSymbolDrawer().draw(READING_ID)


def test_the_bar_counts_only_what_has_been_turned_over() -> None:
    assert reveal_progress(0, 3) == "▱▱▱"
    assert reveal_progress(2, 3) == "▰▰▱"
    assert reveal_progress(3, 3) == "▰▰▰"


def test_the_bar_refuses_to_claim_more_than_the_spread_holds() -> None:
    """A progress indicator that can overstate is the one thing this product must not ship."""

    with pytest.raises(ValueError):
        reveal_progress(4, 3)


def test_each_step_shows_exactly_the_symbols_revealed_so_far() -> None:
    symbols = TarotSymbolDrawer().draw(READING_ID)

    first = render_reveal(TAROT_FLOW.copy, symbols, 1)
    second = render_reveal(TAROT_FLOW.copy, symbols, 2)

    assert symbols[0].display_name in first
    assert symbols[1].display_name not in first
    assert symbols[0].display_name in second and symbols[1].display_name in second
    assert reveal_progress(1, len(symbols)) in first
    assert REVEAL_CLOSING in first


def test_the_revealed_spread_is_the_one_the_reading_will_explain() -> None:
    """The draw is seeded from `reading_id`, so the ritual cannot drift from the result."""

    first = render_reveal(TAROT_FLOW.copy, TarotSymbolDrawer().draw(READING_ID), 3)
    again = render_reveal(TAROT_FLOW.copy, TarotSymbolDrawer().draw(READING_ID), 3)

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

    def draw_symbols(self, reading_id: UUID) -> tuple[ReadingSymbolContext, ...]:
        return TarotSymbolDrawer().draw(reading_id)

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

    await handlers._reveal_spread(message, state, READING_ID, bundle)
    revealed_while_pending = not generation.done()
    use_case.finish.set()
    await generation

    assert revealed_while_pending
    symbols = TarotSymbolDrawer().draw(READING_ID)
    shown = shown_texts(session.methods)
    # The waiting screen is illustrated, so the first symbol arrives as a new photo screen
    # and every later one rewrites its caption: one message per symbol, no more.
    assert len(session.methods) == len(symbols)
    assert shown == [
        render_reveal(TAROT_FLOW.copy, symbols, revealed) for revealed in range(1, len(symbols) + 1)
    ]


async def test_a_persona_without_symbols_simply_waits(
    revealing: tuple[PersonaReadingHandlers, Message, FSMContext, RecordingSession, SlowUseCase],
) -> None:
    handlers, message, state, session, _ = revealing

    class Wordy(SlowUseCase):
        def draw_symbols(self, reading_id: UUID) -> tuple[ReadingSymbolContext, ...]:
            return ()

    await handlers._reveal_spread(message, state, READING_ID, _bundle(Wordy()))

    assert session.methods == []
