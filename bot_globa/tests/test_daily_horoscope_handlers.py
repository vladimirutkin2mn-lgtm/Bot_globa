"""The daily digest is opt-in: the screen states the saved choice and never assumes one."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, SendMessage, SendPhoto, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import CallbackQuery, Chat, Message
from aiogram.types import User as TelegramUser

from app.bot.core_handlers import (
    daily_horoscope_screen,
    daily_horoscope_settings,
    set_daily_horoscope,
)
from app.db.models import User
from app.domain.daily_horoscope import (
    DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
    DailyHoroscopeMode,
    DailyHoroscopePreferenceView,
)
from tests.telegram_doubles import sent, shown_texts


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
        if False:
            yield b""


class FakeOnboarding:
    def __init__(self, *, known: bool = True) -> None:
        self.user = User(id=uuid4(), telegram_user_id=42, first_name="Reader")
        self.known = known

    async def current_user(self, telegram_user_id: int) -> User | None:
        return self.user if self.known and telegram_user_id == 42 else None


class FakePreferences:
    def __init__(self, mode: DailyHoroscopeMode = DailyHoroscopeMode.ON_REQUEST) -> None:
        self.mode = mode
        self.configured: list[tuple[UUID, DailyHoroscopeMode]] = []

    async def current(self, user_id: UUID) -> DailyHoroscopePreferenceView:
        return DailyHoroscopePreferenceView(
            self.mode,
            DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
            None,
        )

    async def configure(
        self,
        user_id: UUID,
        mode: DailyHoroscopeMode,
    ) -> DailyHoroscopePreferenceView:
        self.configured.append((user_id, mode))
        self.mode = mode
        return await self.current(user_id)


@pytest.fixture
async def bot() -> AsyncGenerator[tuple[Bot, RecordingSession], None]:
    session = RecordingSession()
    instance = Bot("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session)
    yield instance, session
    await instance.session.close()


def _callback(bot: Bot, data: str) -> CallbackQuery:
    actor = TelegramUser(id=42, is_bot=False, first_name="Reader")
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        from_user=actor,
        text="menu",
    ).as_(bot)
    return CallbackQuery(
        id="callback",
        from_user=actor,
        chat_instance="chat",
        message=message,
        data=data,
    ).as_(bot)


def _copy(session: RecordingSession) -> list[str]:
    return shown_texts(session.methods)


def _state(bot: Bot) -> FSMContext:
    return FSMContext(MemoryStorage(), StorageKey(bot_id=bot.id, chat_id=42, user_id=42))


def _markup_labels(session: RecordingSession) -> list[str]:
    last = [
        method
        for method in session.methods
        if isinstance(method, SendMessage | SendPhoto) and method.reply_markup is not None
    ][-1]
    markup = last.reply_markup
    assert markup is not None and hasattr(markup, "inline_keyboard")
    return [button.text for row in markup.inline_keyboard for button in row]


async def test_the_digest_screen_offers_the_daily_opt_in(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot

    await daily_horoscope_screen(_callback(instance, "menu:daily"), _state(instance))

    assert "Гороскоп на сегодня" in _copy(session)[-1]
    assert "Получать каждый день" in _markup_labels(session)


async def test_the_settings_screen_states_the_choice_already_saved(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot
    preferences = FakePreferences(DailyHoroscopeMode.MORNING)

    await daily_horoscope_settings(
        _callback(instance, "daily:settings"),
        _state(instance),
        FakeOnboarding(),
        preferences,
    )

    assert "Сейчас: каждое утро, около 08:00." in _copy(session)[-1]
    assert "✓ Да, утром" in _markup_labels(session)


async def test_an_unknown_account_sees_the_default_instead_of_a_saved_choice(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot

    await daily_horoscope_settings(
        _callback(instance, "daily:settings"),
        _state(instance),
        FakeOnboarding(known=False),
        FakePreferences(DailyHoroscopeMode.EVENING),
    )

    assert "Сейчас: только по запросу." in _copy(session)[-1]


async def test_choosing_a_delivery_time_stores_exactly_that_mode(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot
    onboarding = FakeOnboarding()
    preferences = FakePreferences()

    await set_daily_horoscope(
        _callback(instance, "daily:set:evening"),
        _state(instance),
        onboarding,
        preferences,
    )

    assert preferences.configured == [(onboarding.user.id, DailyHoroscopeMode.EVENING)]
    assert "около 20:00" in _copy(session)[-1]


async def test_an_unknown_delivery_mode_changes_nothing(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot
    preferences = FakePreferences()

    await set_daily_horoscope(
        _callback(instance, "daily:set:hourly"),
        _state(instance),
        FakeOnboarding(),
        preferences,
    )

    assert preferences.configured == []
    assert "Не удалось сохранить настройку" in _copy(session)[-1]


async def test_an_account_that_never_started_is_asked_to_start_first(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot
    preferences = FakePreferences()

    await set_daily_horoscope(
        _callback(instance, "daily:set:morning"),
        _state(instance),
        FakeOnboarding(known=False),
        preferences,
    )

    assert preferences.configured == []
    assert _copy(session)[-1] == "Сначала отправьте /start."
    assert isinstance(session.methods[0], AnswerCallbackQuery)
