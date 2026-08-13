"""Quick reading feedback must prove ownership and stay free of user content."""

from collections.abc import AsyncGenerator, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import AnswerCallbackQuery, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import CallbackQuery, Chat, Message
from aiogram.types import User as TelegramUser

from app.bot.reading_feedback_handlers import submit_reading_feedback
from app.db.models import User
from app.providers.analytics import OracleProductEvent
from app.services.oracle_product_analytics import OracleProductAnalytics


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


class FakeOnboarding:
    def __init__(self) -> None:
        self.user = User(id=uuid4(), telegram_user_id=42, first_name="Reader")

    async def current_user(self, telegram_user_id: int) -> User | None:
        return self.user if telegram_user_id == 42 else None


class FakeHistory:
    def __init__(self, owned: UUID | None) -> None:
        self.owned = owned

    async def owns_full(self, user_id: UUID, reading_id: UUID) -> bool:
        return self.owned is not None and reading_id == self.owned


class RecordingAnalytics:
    def __init__(self) -> None:
        self.events: list[tuple[str | None, str, Mapping[str, str]]] = []

    async def track(
        self,
        user_id: str | None,
        event: str,
        properties: Mapping[str, str] | None = None,
    ) -> None:
        self.events.append((user_id, event, properties or {}))


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
        text="result",
    ).as_(bot)
    return CallbackQuery(
        id="callback",
        from_user=actor,
        chat_instance="chat",
        message=message,
        data=data,
    ).as_(bot)


def _answers(session: RecordingSession) -> list[AnswerCallbackQuery]:
    return [method for method in session.methods if isinstance(method, AnswerCallbackQuery)]


async def test_feedback_on_an_owned_paid_reading_is_recorded_without_content(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot
    reading_id = uuid4()
    onboarding = FakeOnboarding()
    analytics = RecordingAnalytics()

    await submit_reading_feedback(
        _callback(instance, f"rfb:hit:{reading_id}"),
        onboarding,
        FakeHistory(reading_id),
        OracleProductAnalytics(analytics),
    )

    assert len(analytics.events) == 1
    user_id, event, properties = analytics.events[0]
    assert user_id == str(onboarding.user.id)
    assert event == OracleProductEvent.READING_FEEDBACK_SUBMITTED.value
    assert properties["reading_id"] == str(reading_id)
    assert properties["reaction_code"] == "hit"
    assert _answers(session)[-1].show_alert is not True


async def test_feedback_on_someone_elses_reading_is_refused_and_not_recorded(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot
    analytics = RecordingAnalytics()

    await submit_reading_feedback(
        _callback(instance, f"rfb:miss:{uuid4()}"),
        FakeOnboarding(),
        FakeHistory(None),
        OracleProductAnalytics(analytics),
    )

    assert analytics.events == []
    assert _answers(session)[-1].show_alert is True


async def test_a_malformed_feedback_callback_is_refused_without_a_lookup(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot
    analytics = RecordingAnalytics()

    await submit_reading_feedback(
        _callback(instance, "rfb:hit:not-a-reading"),
        FakeOnboarding(),
        FakeHistory(uuid4()),
        OracleProductAnalytics(analytics),
    )

    assert analytics.events == []
    assert _answers(session)[-1].show_alert is True
