"""Core aiogram handler tests and reusable Telegram test harness."""

from collections.abc import AsyncGenerator, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import CommandStart
from aiogram.methods import AnswerCallbackQuery, SendMessage, SendPhoto, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update
from aiogram.types import User as TelegramUser

from app.bot import texts
from app.bot.core_handlers import privacy_screen, router, start
from app.bot.persona_flow import QUESTION_EXAMPLE, QUESTION_PROMPT
from app.bot.persona_flows import TAROT_FLOW
from app.bot.persona_handlers import create_persona_router
from app.bot.rate_limit import FixedWindowRateLimiter, RateLimitMiddleware
from app.bot.states import OnboardingStates
from app.db.models import User
from app.services.onboarding import OnboardingService, TelegramIdentity

type Harness = tuple[Dispatcher, Bot, "RecordingSession", "MemoryUsers", OnboardingService]


class RecordingSession(AiohttpSession):
    def __init__(self) -> None:
        super().__init__()
        self.methods: list[TelegramMethod[Any]] = []
        self.fail_text: str | None = None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,  # noqa: ASYNC109 -- aiogram API
    ) -> TelegramType:
        self.methods.append(method)
        if isinstance(method, SendMessage) and method.text == self.fail_text:
            self.fail_text = None
            raise RuntimeError("SECRET-PRIVATE-CONTENT")
        if isinstance(method, SendMessage):
            return cast(
                "TelegramType",
                Message(
                    message_id=len(self.methods) + 100,
                    date=datetime.now(UTC),
                    chat=Chat(id=int(method.chat_id), type="private"),
                    text=method.text,
                ),
            )
        return cast("TelegramType", True)

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109 -- aiogram API
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        if False:  # pragma: no cover - required async-generator shape
            yield b""


class MemoryUsers:
    def __init__(self) -> None:
        self.users: dict[int, User] = {}

    async def get_or_create(
        self,
        telegram_user_id: int,
        username: str | None,
        first_name: str,
        language: str | None,
    ) -> tuple[User, bool]:
        existing = self.users.get(telegram_user_id)
        if existing:
            return existing, False
        user = User(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            telegram_username=username,
            first_name=first_name,
            telegram_language=language,
            age_confirmed=False,
            onboarding_completed=False,
        )
        self.users[telegram_user_id] = user
        return user, True

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        return self.users.get(telegram_user_id)

    async def save(self, user: User) -> None:
        assert user.telegram_user_id is not None
        self.users[user.telegram_user_id] = user


class NoOpAnalytics:
    async def track(
        self,
        user_id: str | None,
        event: str,
        properties: Mapping[str, str] | None = None,
    ) -> None:
        return None


dispatcher = Dispatcher()
dispatcher.include_router(router)


@pytest.fixture
async def harness() -> AsyncGenerator[Harness, None]:
    session = RecordingSession()
    bot = Bot("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session)
    users = MemoryUsers()
    service = OnboardingService(users, NoOpAnalytics())
    yield dispatcher, bot, session, users, service
    await bot.session.close()


def telegram_user(user_id: int = 42) -> TelegramUser:
    return TelegramUser(
        id=user_id,
        is_bot=False,
        first_name="Анна",
        username="anna",
        language_code="ru",
    )


def start_update(update_id: int = 1, user_id: int = 42) -> Update:
    user = telegram_user(user_id)
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=user,
            text="/start",
            entities=[MessageEntity(type="bot_command", offset=0, length=6)],
        ),
    )


def callback_update(data: str, update_id: int = 2, user_id: int = 42) -> Update:
    user = telegram_user(user_id)
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"callback-{update_id}",
            from_user=user,
            chat_instance="test",
            data=data,
            message=Message(
                message_id=10,
                date=datetime.now(UTC),
                chat=Chat(id=user_id, type="private"),
                from_user=user,
                text="button",
            ),
        ),
    )


def message_update(text: str | None, update_id: int, user_id: int = 42) -> Update:
    user = telegram_user(user_id)
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=user,
            text=text,
            photo=[] if text is None else None,
        ),
    )


def sent_texts(session: RecordingSession) -> list[str]:
    return [
        method.text if isinstance(method, SendMessage) else method.caption or ""
        for method in session.methods
        if isinstance(method, (SendMessage, SendPhoto))
    ]


async def complete(service: OnboardingService, user_id: int = 42) -> None:
    await service.start(TelegramIdentity(user_id, "anna", "Анна", "ru"))
    await service.accept_consent(user_id)


async def test_new_and_repeated_start_show_intro_without_duplicate(harness: Harness) -> None:
    local_dispatcher, bot, session, users, service = harness
    await local_dispatcher.feed_update(bot, start_update(), onboarding=service)
    await local_dispatcher.feed_update(bot, start_update(2), onboarding=service)
    assert sent_texts(session) == [texts.WELCOME, texts.WELCOME]
    assert len(users.users) == 1


async def test_intro_continuation_shows_intent_menu_before_consent(harness: Harness) -> None:
    local_dispatcher, bot, session, _, service = harness
    await local_dispatcher.feed_update(bot, start_update(), onboarding=service)
    await local_dispatcher.feed_update(
        bot,
        callback_update("onboarding:intro"),
        onboarding=service,
    )
    assert sent_texts(session)[-1] == texts.MAIN_MENU
    assert not await service.analysis_allowed(42)


async def test_consent_acceptance_and_completed_start_show_menu(harness: Harness) -> None:
    local_dispatcher, bot, session, _, service = harness
    await local_dispatcher.feed_update(bot, start_update(), onboarding=service)
    await local_dispatcher.feed_update(
        bot,
        callback_update("onboarding:intro"),
        onboarding=service,
    )
    await local_dispatcher.feed_update(
        bot,
        callback_update("onboarding:consent", 3),
        onboarding=service,
    )
    await local_dispatcher.feed_update(bot, start_update(4), onboarding=service)
    assert sent_texts(session)[-2:] == [texts.MAIN_MENU, texts.MAIN_MENU]


async def test_a_stale_intro_button_does_not_reopen_consent_for_a_completed_user(
    harness: Harness,
) -> None:
    local_dispatcher, bot, session, _, service = harness
    await complete(service)

    await local_dispatcher.feed_update(
        bot,
        callback_update("onboarding:intro"),
        onboarding=service,
    )

    assert sent_texts(session)[-1] == texts.MAIN_MENU
    context = local_dispatcher.fsm.get_context(bot=bot, chat_id=42, user_id=42)
    assert await context.get_state() is None


async def test_selected_persona_requests_just_in_time_consent_then_resumes_that_flow() -> None:
    local_dispatcher = Dispatcher()
    local_dispatcher.include_router(create_persona_router(TAROT_FLOW))
    session = RecordingSession()
    bot = Bot("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session)
    users = MemoryUsers()
    service = OnboardingService(users, NoOpAnalytics())
    await service.start(TelegramIdentity(42, "anna", "Анна", "ru"))
    try:
        await local_dispatcher.feed_update(
            bot,
            callback_update("menu:tarot"),
            onboarding=service,
            privacy_retention_days=30,
        )
        context = local_dispatcher.fsm.get_context(bot=bot, chat_id=42, user_id=42)
        assert await context.get_state() == OnboardingStates.waiting_for_consent.state
        assert sent_texts(session)[-1] == texts.CONSENT.format(days=30)
        assert not await service.analysis_allowed(42)

        await local_dispatcher.feed_update(
            bot,
            callback_update("onboarding:consent:tarot", 3),
            onboarding=service,
        )
        assert await service.analysis_allowed(42)
        assert sent_texts(session)[-1] == TAROT_FLOW.texts.welcome

        await local_dispatcher.feed_update(
            bot,
            callback_update("tarot:topic:decision", 4),
            onboarding=service,
        )
        assert sent_texts(session)[-1] == QUESTION_PROMPT
        await local_dispatcher.feed_update(
            bot,
            callback_update("tarot:example", 5),
            onboarding=service,
        )
        assert sent_texts(session)[-1] == QUESTION_EXAMPLE.format(
            example=TAROT_FLOW.topic_examples["decision"]
        )
    finally:
        await bot.session.close()


@pytest.mark.parametrize("data", ["onboarding:intro", "onboarding:consent"])
async def test_onboarding_callback_without_prior_start_is_handled(
    harness: Harness,
    data: str,
) -> None:
    local_dispatcher, bot, session, users, service = harness
    await local_dispatcher.feed_update(bot, callback_update(data), onboarding=service)
    assert 42 in users.users
    assert any(isinstance(method, AnswerCallbackQuery) for method in session.methods)


async def test_rate_limit_middleware_applies_to_start_and_callbacks() -> None:
    limited_dispatcher = Dispatcher()
    limited_dispatcher.message.outer_middleware(
        RateLimitMiddleware(FixedWindowRateLimiter(limit=1))
    )
    limited_dispatcher.callback_query.outer_middleware(
        RateLimitMiddleware(FixedWindowRateLimiter(limit=1))
    )
    rate_router = Router()
    rate_router.message.register(start, CommandStart())
    rate_router.callback_query.register(privacy_screen, F.data == "menu:privacy")
    limited_dispatcher.include_router(rate_router)
    session = RecordingSession()
    bot = Bot("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session)
    users = MemoryUsers()
    service = OnboardingService(users, NoOpAnalytics())
    await limited_dispatcher.feed_update(bot, start_update(), onboarding=service)
    await limited_dispatcher.feed_update(bot, start_update(2), onboarding=service)
    await limited_dispatcher.feed_update(
        bot,
        callback_update("menu:privacy", 3),
        onboarding=service,
        privacy_retention_days=30,
    )
    await limited_dispatcher.feed_update(
        bot,
        callback_update("menu:privacy", 4),
        onboarding=service,
        privacy_retention_days=30,
    )
    assert sent_texts(session).count(texts.RATE_LIMITED) == 1
    alerts = [method for method in session.methods if isinstance(method, AnswerCallbackQuery)]
    assert any(method.text == texts.RATE_LIMITED and method.show_alert for method in alerts)
    await bot.session.close()
