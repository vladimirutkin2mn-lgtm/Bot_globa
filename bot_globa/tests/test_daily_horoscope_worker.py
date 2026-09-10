"""The text-only daily broadcast preserves its at-most-once Telegram boundary."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any, cast
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage, SendPhoto, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import InlineKeyboardMarkup

from app.domain.daily_horoscope import DailyHoroscopeClaim, DailyHoroscopeMode
from app.domain.natal_chart import ZodiacSign
from app.workers import daily_horoscope as worker


def _throttled() -> TelegramRetryAfter:
    return TelegramRetryAfter(
        method=SendMessage(chat_id=1, text="x"),
        message="Too Many Requests: retry after 1",
        retry_after=1,
    )


class RecordingSession(AiohttpSession):
    def __init__(self, failures: int = 0, error: Exception | None = None) -> None:
        super().__init__()
        self.failures = failures
        self.error = error or _throttled()
        self.attempts = 0
        self.methods: list[TelegramMethod[Any]] = []

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,  # noqa: ASYNC109 -- aiogram session contract
    ) -> TelegramType:
        self.attempts += 1
        self.methods.append(method)
        if self.attempts <= self.failures:
            raise self.error
        return cast("TelegramType", True)

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109 -- aiogram session contract
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        if False:
            yield b""


def _claim() -> DailyHoroscopeClaim:
    return DailyHoroscopeClaim(
        claim_id=uuid4(),
        user_id=uuid4(),
        telegram_user_id=4242,
        delivery_date=date(2026, 8, 13),
        mode=DailyHoroscopeMode.MORNING,
    )


def _text() -> str:
    return "Гороскоп на сегодня · 13.08.2026\nЭто общий прогноз по знаку."


def _bot(session: RecordingSession) -> Bot:
    return Bot(token="42:TEST", session=session)


def _labels(method: SendMessage) -> list[str]:
    markup = method.reply_markup
    assert isinstance(markup, InlineKeyboardMarkup)
    return [button.text for row in markup.inline_keyboard for button in row]


async def test_a_throttled_text_send_is_retried_against_the_same_claim() -> None:
    session = RecordingSession(failures=2)
    bot = _bot(session)
    try:
        await worker._send_digest(
            bot,
            _claim(),
            _text(),
            zodiac_sign=ZodiacSign.ARIES,
            max_attempts=4,
            stopped=asyncio.Event(),
        )
    finally:
        await bot.session.close()

    assert session.attempts == 3
    sent = [method for method in session.methods if isinstance(method, SendMessage)][-1]
    assert "Гороскоп на сегодня · 13.08.2026" in sent.text
    assert "Все знаки" in _labels(sent)
    assert "Сменить знак" in _labels(sent)
    assert not any(isinstance(method, SendPhoto) for method in session.methods)


async def test_an_unselected_sign_keeps_the_all_signs_entry_point() -> None:
    session = RecordingSession()
    bot = _bot(session)
    try:
        await worker._send_digest(
            bot,
            _claim(),
            _text(),
            zodiac_sign=None,
            max_attempts=1,
            stopped=asyncio.Event(),
        )
    finally:
        await bot.session.close()

    sent = [method for method in session.methods if isinstance(method, SendMessage)][-1]
    assert "Выбрать свой знак" in _labels(sent)


async def test_throttling_past_the_retry_budget_surfaces_to_the_caller() -> None:
    session = RecordingSession(failures=5)
    bot = _bot(session)
    try:
        with pytest.raises(TelegramRetryAfter):
            await worker._send_digest(
                bot,
                _claim(),
                _text(),
                zodiac_sign=None,
                max_attempts=2,
                stopped=asyncio.Event(),
            )
    finally:
        await bot.session.close()

    assert session.attempts == 2


async def test_shutdown_during_a_retry_stops_instead_of_waiting_out_the_limit() -> None:
    session = RecordingSession(failures=5)
    bot = _bot(session)
    stopped = asyncio.Event()
    stopped.set()
    try:
        with pytest.raises(TelegramRetryAfter):
            await worker._send_digest(
                bot,
                _claim(),
                _text(),
                zodiac_sign=None,
                max_attempts=4,
                stopped=stopped,
            )
    finally:
        await bot.session.close()

    assert session.attempts == 1


async def test_a_blocked_recipient_is_not_retried() -> None:
    session = RecordingSession(
        failures=5,
        error=TelegramForbiddenError(
            method=SendMessage(chat_id=1, text="x"),
            message="Forbidden: bot was blocked by the user",
        ),
    )
    bot = _bot(session)
    try:
        with pytest.raises(TelegramForbiddenError):
            await worker._send_digest(
                bot,
                _claim(),
                _text(),
                zodiac_sign=None,
                max_attempts=4,
                stopped=asyncio.Event(),
            )
    finally:
        await bot.session.close()

    assert session.attempts == 1
