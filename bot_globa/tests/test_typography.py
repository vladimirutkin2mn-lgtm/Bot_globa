"""Markup carries meaning, and a markup mistake never costs the user a message."""

from collections.abc import AsyncGenerator
from typing import Any, cast
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.methods.base import TelegramType

from app.bot.persona_flows import TAROT_FLOW
from app.bot.reading_renderer import render_full
from app.bot.typography import create_bot, quote
from app.domain.reading import SymbolOrientation
from app.domain.reading_result import (
    ReadingResult,
    ReadingSafetyAssessment,
    ReadingScenario,
    ReadingSymbolResult,
    ShareCardPayload,
)
from app.services.persona_reading import PersonaPreviewOutcome
from app.services.reading_generation import ReadingGenerationResult, ReadingGenerationStatus

INJECTED = "<b>полужирный</b> & <script>alert(1)</script>"


class FlakySession(AiohttpSession):
    """Refuse the first parsed message the way Telegram refuses a broken tag."""

    def __init__(self) -> None:
        super().__init__()
        self.methods: list[TelegramMethod[Any]] = []
        self.refusals = 0
        self.error = "Bad Request: can't parse entities: unsupported start tag"

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,  # noqa: ASYNC109 -- aiogram session contract
    ) -> TelegramType:
        self.methods.append(method)
        if self.refusals > 0:
            self.refusals -= 1
            raise TelegramBadRequest(method=method, message=self.error)
        return cast("TelegramType", True)

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


@pytest.fixture
async def bot() -> AsyncGenerator[tuple[Bot, FlakySession], None]:
    session = FlakySession()
    instance = create_bot("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session)
    yield instance, session
    await instance.session.close()


def _outcome(interpretation: str) -> PersonaPreviewOutcome:
    result = ReadingResult(
        title=INJECTED,
        opening="Разбор о выборе.",
        symbols=[
            ReadingSymbolResult(
                symbol_id="major_16",
                position="1",
                orientation=SymbolOrientation.UPRIGHT,
                interpretation=interpretation,
            )
        ],
        patterns=["Отделить срочное от важного."],
        possible_scenarios=[
            ReadingScenario(scenario="Пауза проясняет обмен.", conditions=["Записать обратимое."])
        ],
        reflection_questions=["Что нужно защитить?"],
        practical_step="Сделать один звонок.",
        uncertainty_note="Расклад не определяет внешние события.",
        share_card=ShareCardPayload(headline="Пауза", short_text="Пауза перед выбором."),
        safety=ReadingSafetyAssessment(high_risk_detected=False, categories=[]),
    )
    return PersonaPreviewOutcome(
        reading_id=uuid4(),
        generation=ReadingGenerationResult(ReadingGenerationStatus.COMPLETED, result=result),
        symbols=(),
        symbol_set_code=None,
    )


def test_quote_neutralises_markup_without_mangling_ordinary_punctuation() -> None:
    assert quote("<b>x</b> & y") == "&lt;b&gt;x&lt;/b&gt; &amp; y"
    assert quote("вопрос — «важно», 5 > 3") == "вопрос — «важно», 5 &gt; 3"


def test_a_model_answer_cannot_inject_its_own_markup_into_a_reading() -> None:
    rendered = "\n".join(render_full(_outcome(INJECTED), TAROT_FLOW.copy))

    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    # The renderer's own emphasis survives; only the model's markup is neutralised.
    assert f"<b>{TAROT_FLOW.copy.practical_step_title}:</b>" in rendered


def test_every_message_is_parsed_as_html_by_default(bot: tuple[Bot, FlakySession]) -> None:
    instance, _ = bot

    assert instance.default.parse_mode == ParseMode.HTML


async def test_a_message_telegram_refuses_to_parse_is_sent_again_as_plain_text(
    bot: tuple[Bot, FlakySession],
) -> None:
    instance, session = bot
    session.refusals = 1

    await instance.send_message(chat_id=42, text="<b>незакрытый")

    assert len(session.methods) == 2
    retried = session.methods[-1]
    assert isinstance(retried, SendMessage)
    assert retried.parse_mode is None
    assert retried.text == "<b>незакрытый"


async def test_an_unrelated_bad_request_is_not_retried(
    bot: tuple[Bot, FlakySession],
) -> None:
    instance, session = bot
    session.refusals = 1
    session.error = "Bad Request: chat not found"

    with pytest.raises(TelegramBadRequest):
        await instance.send_message(chat_id=42, text="Привет")

    assert len(session.methods) == 1
