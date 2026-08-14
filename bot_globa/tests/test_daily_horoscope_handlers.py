"""The daily digest is default-on and lets the user control delivery and local time."""

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
    request_daily_horoscope_timezone,
    set_daily_horoscope,
    set_daily_horoscope_timezone,
)
from app.bot.states import DailyHoroscopeStates
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
    def __init__(self, mode: DailyHoroscopeMode = DailyHoroscopeMode.MORNING) -> None:
        self.mode = mode
        self.timezone = DEFAULT_DAILY_HOROSCOPE_TIMEZONE
        self.configured: list[tuple[UUID, DailyHoroscopeMode]] = []
        self.differences: list[tuple[UUID, int]] = []

    async def current(self, user_id: UUID) -> DailyHoroscopePreferenceView:
        return DailyHoroscopePreferenceView(
            self.mode,
            self.timezone,
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

    async def set_moscow_time_difference(
        self,
        user_id: UUID,
        difference: int,
    ) -> DailyHoroscopePreferenceView:
        self.differences.append((user_id, difference))
        self.timezone = {2: "Etc/GMT-5", -1: "Etc/GMT-2"}.get(
            difference,
            DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
        )
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


def _message(bot: Bot, text: str) -> Message:
    actor = TelegramUser(id=42, is_bot=False, first_name="Reader")
    return Message(
        message_id=2,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        from_user=actor,
        text=text,
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


async def test_the_digest_screen_opens_its_settings(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot

    await daily_horoscope_screen(
        _callback(instance, "menu:daily"),
        _state(instance),
        FakeOnboarding(),
        FakePreferences(),
    )

    assert "Гороскоп на сегодня" in _copy(session)[-1]
    assert "Настройки" in _markup_labels(session)


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

    assert "Ежедневная отправка: включена." in _copy(session)[-1]
    assert "Время отправки: 08:00 по вашему времени." in _copy(session)[-1]
    assert "Отключить ежедневный гороскоп" in _markup_labels(session)
    assert "Изменить часовой пояс" in _markup_labels(session)


async def test_an_unknown_account_sees_the_enabled_default(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot

    await daily_horoscope_settings(
        _callback(instance, "daily:settings"),
        _state(instance),
        FakeOnboarding(known=False),
        FakePreferences(DailyHoroscopeMode.EVENING),
    )

    assert "Ежедневная отправка: включена." in _copy(session)[-1]
    assert "Разница с Москвой: 0 ч." in _copy(session)[-1]


async def test_a_stale_evening_button_is_normalized_to_the_new_morning_schedule(
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

    assert preferences.configured == [(onboarding.user.id, DailyHoroscopeMode.MORNING)]
    assert "каждый день в 08:00 по вашему времени" in _copy(session)[-1]


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


async def test_timezone_setting_asks_for_a_difference_from_moscow(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot
    state = _state(instance)

    await request_daily_horoscope_timezone(
        _callback(instance, "daily:timezone"),
        state,
        FakeOnboarding(),
    )

    assert "Напишите одним сообщением" in _copy(session)[-1]
    assert "Екатеринбург — +2" in _copy(session)[-1]
    assert await state.get_state() == DailyHoroscopeStates.waiting_for_timezone_difference.state


async def test_timezone_difference_is_saved_and_keeps_delivery_enabled(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot
    state = _state(instance)
    onboarding = FakeOnboarding()
    preferences = FakePreferences()
    await state.set_state(DailyHoroscopeStates.waiting_for_timezone_difference)

    await set_daily_horoscope_timezone(
        _message(instance, "+2"),
        state,
        onboarding,
        preferences,
    )

    assert preferences.differences == [(onboarding.user.id, 2)]
    assert "Разница с Москвой — +2 ч" in _copy(session)[-1]
    assert "Разница с Москвой: +2 ч." in _copy(session)[-1]
    assert await state.get_state() is None


async def test_invalid_timezone_difference_keeps_the_input_open(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot
    state = _state(instance)
    await state.set_state(DailyHoroscopeStates.waiting_for_timezone_difference)

    await set_daily_horoscope_timezone(
        _message(instance, "+20"),
        state,
        FakeOnboarding(),
        FakePreferences(),
    )

    assert "целое число от -15 до +11" in _copy(session)[-1]
    assert await state.get_state() == DailyHoroscopeStates.waiting_for_timezone_difference.state
