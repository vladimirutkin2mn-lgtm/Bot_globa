"""The broadcast survives Telegram throttling instead of forfeiting the digest.

Every active user shares one local 08:00, so a 429 is an expected outcome of the burst
rather than an exceptional one. `claim_due` reserves `last_delivered_on` before the send,
which means a throttled delivery that falls through to `release()` loses the day for good.
These tests pin the one failure Telegram reports unambiguously to a retry against the same
claim, and keep every ambiguous failure on the at-most-once path.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import date
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardMarkup

from app.bot.scene_media import Scene
from app.domain.daily_horoscope import DailyHoroscopeClaim, DailyHoroscopeMode
from app.services.daily_sky import build_daily_horoscope
from app.workers import daily_horoscope as worker


def _throttled() -> TelegramRetryAfter:
    return TelegramRetryAfter(
        method=SendMessage(chat_id=1, text="x"),
        message="Too Many Requests: retry after 1",
        retry_after=1,
    )


class RecordingSender:
    """Stand in for `send_scene_photo`, failing the first `failures` deliveries."""

    def __init__(self, failures: int, error: Exception | None = None) -> None:
        self.attempts = 0
        self.captions: list[str] = []
        self._failures = failures
        self._error = error or _throttled()

    async def __call__(
        self,
        bot: Bot,
        chat_id: int,
        scene: Scene,
        caption: str,
        *,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        self.attempts += 1
        if self.attempts <= self._failures:
            raise self._error
        self.captions.append(caption)


InstallSender = Callable[[int, Exception | None], RecordingSender]


@pytest.fixture
def sender(monkeypatch: pytest.MonkeyPatch) -> InstallSender:
    def install(failures: int, error: Exception | None = None) -> RecordingSender:
        recorder = RecordingSender(failures, error)
        monkeypatch.setattr(worker, "send_scene_photo", recorder)
        return recorder

    return install


@pytest.fixture
async def bot() -> AsyncGenerator[Bot, None]:
    instance = Bot(token="42:TEST")
    try:
        yield instance
    finally:
        await instance.session.close()


def _claim() -> DailyHoroscopeClaim:
    return DailyHoroscopeClaim(
        claim_id=uuid4(),
        user_id=uuid4(),
        telegram_user_id=4242,
        delivery_date=date(2026, 8, 13),
        mode=DailyHoroscopeMode.MORNING,
    )


def _snapshot():
    return build_daily_horoscope(date(2026, 8, 13))


async def test_a_throttled_send_is_retried_against_the_same_claim(
    bot: Bot,
    sender: InstallSender,
) -> None:
    recorder = sender(2, None)

    await worker._send_digest(
        bot,
        _claim(),
        _snapshot(),
        max_attempts=4,
        stopped=asyncio.Event(),
    )

    assert recorder.attempts == 3
    assert "Гороскоп на сегодня · 13.08.2026" in recorder.captions[0]
    assert "персональный учитывает вашу натальную карту" in recorder.captions[0]


async def test_throttling_past_the_retry_budget_surfaces_to_the_caller(
    bot: Bot,
    sender: InstallSender,
) -> None:
    """Exhausting the budget must reach the worker's ambiguous-failure path, not pass."""

    recorder = sender(5, None)

    with pytest.raises(TelegramRetryAfter):
        await worker._send_digest(
            bot,
            _claim(),
            _snapshot(),
            max_attempts=2,
            stopped=asyncio.Event(),
        )

    assert recorder.attempts == 2


async def test_shutdown_during_a_retry_stops_instead_of_waiting_out_the_limit(
    bot: Bot,
    sender: InstallSender,
) -> None:
    recorder = sender(5, None)
    stopped = asyncio.Event()
    stopped.set()

    with pytest.raises(TelegramRetryAfter):
        await worker._send_digest(
            bot,
            _claim(),
            _snapshot(),
            max_attempts=4,
            stopped=stopped,
        )

    assert recorder.attempts == 1


async def test_a_blocked_recipient_is_not_retried(bot: Bot, sender: InstallSender) -> None:
    """Only a rate limit is retried; a permanent rejection must reach the caller at once."""

    recorder = sender(
        5,
        TelegramForbiddenError(
            method=SendMessage(chat_id=1, text="x"),
            message="Forbidden: bot was blocked by the user",
        ),
    )

    with pytest.raises(TelegramForbiddenError):
        await worker._send_digest(
            bot,
            _claim(),
            _snapshot(),
            max_attempts=4,
            stopped=asyncio.Event(),
        )

    assert recorder.attempts == 1
