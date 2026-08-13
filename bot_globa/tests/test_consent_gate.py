"""CJM v2 opened the menu before the terms, so every personal-data screen gates itself."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

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

from app.bot import texts
from app.bot.core_handlers import balance_screen, buy_credits
from app.bot.horoscope_handlers import HoroscopeHandlers
from app.bot.persona_flows import TAROT_FLOW
from app.bot.persona_handlers import PersonaReadingHandlers
from app.bot.states import OnboardingStates
from app.config import Settings
from app.db.models import User
from app.domain.billing import BillingCatalog

RETENTION_DAYS = 45


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
        if isinstance(method, AnswerCallbackQuery):
            return cast("TelegramType", True)
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


class UnconsentedOnboarding:
    """A started account that never accepted the terms."""

    def __init__(self) -> None:
        self.user = User(id=uuid4(), telegram_user_id=42, first_name="Buyer")
        self.started = 0

    async def current_user(self, telegram_user_id: int) -> User | None:
        return self.user if telegram_user_id == 42 else None

    async def analysis_allowed(self, telegram_user_id: int) -> bool:
        return False

    async def start(self, identity: object) -> None:
        self.started += 1


class FailingCredits:
    async def balance(self, user_id: object) -> int:  # pragma: no cover - must not be reached
        raise AssertionError("balance must not be read before the terms are accepted")


class FailingPayments:
    async def create_checkout(
        self, user_id: object, product: str
    ) -> object:  # pragma: no cover - must not be reached
        raise AssertionError("a checkout must not start before the terms are accepted")


@pytest.fixture
async def context() -> AsyncGenerator[
    tuple[RecordingSession, FSMContext, CallbackQuery, UnconsentedOnboarding], None
]:
    session = RecordingSession()
    bot = Bot("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session)
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=bot.id, chat_id=42, user_id=42))
    actor = TelegramUser(id=42, is_bot=False, first_name="Buyer")
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        from_user=actor,
        text="button",
    ).as_(bot)
    callback = CallbackQuery(
        id="callback",
        from_user=actor,
        chat_instance="chat",
        message=message,
        data="menu:balance",
    ).as_(bot)
    yield session, state, callback, UnconsentedOnboarding()
    await bot.session.close()


def texts_sent(session: RecordingSession) -> list[str]:
    return [
        method.text if isinstance(method, SendMessage) else method.caption or ""
        for method in session.methods
        if isinstance(method, SendMessage | SendPhoto)
    ]


async def test_balance_requires_the_terms_before_reading_an_account(
    context: tuple[RecordingSession, FSMContext, CallbackQuery, UnconsentedOnboarding],
    settings: Settings,
) -> None:
    session, state, callback, onboarding = context

    await balance_screen(
        callback,
        state,
        onboarding,
        FailingCredits(),
        BillingCatalog(settings),
        settings,
        RETENTION_DAYS,
    )

    assert texts_sent(session)[-1] == texts.CONSENT.format(days=RETENTION_DAYS)
    assert await state.get_state() == OnboardingStates.waiting_for_consent.state


async def test_a_purchase_requires_the_terms_before_a_checkout_is_created(
    context: tuple[RecordingSession, FSMContext, CallbackQuery, UnconsentedOnboarding],
    settings: Settings,
) -> None:
    session, state, callback, onboarding = context
    buying = callback.model_copy(update={"data": "credits:buy:reading_single"}).as_(callback.bot)

    await buy_credits(
        buying,
        state,
        onboarding,
        FailingPayments(),
        BillingCatalog(settings),
        settings,
        RETENTION_DAYS,
    )

    assert texts_sent(session)[-1] == texts.CONSENT.format(days=RETENTION_DAYS)
    assert await state.get_state() == OnboardingStates.waiting_for_consent.state


async def test_the_gate_states_the_configured_retention_window(
    context: tuple[RecordingSession, FSMContext, CallbackQuery, UnconsentedOnboarding],
    settings: Settings,
) -> None:
    session, state, callback, onboarding = context

    await balance_screen(
        callback,
        state,
        onboarding,
        FailingCredits(),
        BillingCatalog(settings),
        settings,
        7,
    )

    assert "7 дней" in texts_sent(session)[-1]


async def test_a_stale_persona_question_state_cannot_store_personal_text(
    context: tuple[RecordingSession, FSMContext, CallbackQuery, UnconsentedOnboarding],
) -> None:
    session, state, callback, onboarding = context
    message = callback.message
    assert isinstance(message, Message)
    message = message.model_copy(update={"text": "Мой личный вопрос"}).as_(callback.bot)
    await state.update_data(topic="decision")

    await PersonaReadingHandlers(TAROT_FLOW).receive_question(
        message,
        state,
        cast("Any", onboarding),
        {},
        RETENTION_DAYS,
    )

    assert "question" not in await state.get_data()
    assert await state.get_state() == OnboardingStates.waiting_for_consent.state
    assert texts_sent(session)[-1] == texts.CONSENT.format(days=RETENTION_DAYS)


async def test_a_stale_birth_intake_state_cannot_store_birth_data(
    context: tuple[RecordingSession, FSMContext, CallbackQuery, UnconsentedOnboarding],
) -> None:
    session, state, callback, onboarding = context
    message = callback.message
    assert isinstance(message, Message)
    message = message.model_copy(update={"text": "12.07.1990"}).as_(callback.bot)

    await HoroscopeHandlers().receive_birth_date(
        message,
        state,
        cast("Any", onboarding),
        RETENTION_DAYS,
    )

    assert "birth_date" not in await state.get_data()
    assert await state.get_state() == OnboardingStates.waiting_for_consent.state
    assert texts_sent(session)[-1] == texts.CONSENT.format(days=RETENTION_DAYS)
