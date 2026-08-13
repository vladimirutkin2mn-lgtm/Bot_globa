"""Telegram's own surfaces: the command menu and the links that skip it."""

import inspect
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    SetChatMenuButton,
    SetMyCommands,
    TelegramMethod,
)
from aiogram.methods.base import TelegramType
from aiogram.types import Chat, Message, MessageEntity, Update
from aiogram.types import User as TelegramUser

from app.bot import main as app_main
from app.bot.commands import BOT_COMMANDS, configure_commands
from app.bot.main import prepare_runtime
from app.bot.persona_flows import TAROT_FLOW
from app.bot.persona_handlers import create_persona_router
from app.services.onboarding import OnboardingService, TelegramIdentity
from app.services.persona_registry import PersonaRegistryService, PersonaSyncResult
from app.workers import telegram as telegram_worker
from tests.telegram_doubles import sent, shown_texts

RETENTION_DAYS = 30


class RecordingPersonaRegistry:
    def __init__(self) -> None:
        self.syncs = 0

    async def sync_mvp_personas(self) -> PersonaSyncResult:
        self.syncs += 1
        return PersonaSyncResult(created=4, updated=0, unchanged=0)


class RecordingSession(AiohttpSession):
    def __init__(self) -> None:
        super().__init__()
        self.methods: list[TelegramMethod[Any]] = []
        self.refuse: Exception | None = None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,  # noqa: ASYNC109 -- aiogram session contract
    ) -> TelegramType:
        self.methods.append(method)
        if self.refuse is not None:
            raise self.refuse
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


class NoOpAnalytics:
    async def track(self, user_id: str | None, event: str, properties: Any = None) -> None:
        return None


class MemoryUsers:
    def __init__(self) -> None:
        self.users: dict[int, Any] = {}

    async def get_or_create(
        self,
        telegram_user_id: int,
        username: str | None,
        first_name: str,
        language: str | None,
    ) -> tuple[Any, bool]:
        from uuid import uuid4

        from app.db.models import User

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

    async def get_by_telegram_id(self, telegram_user_id: int) -> Any:
        return self.users.get(telegram_user_id)

    async def save(self, user: Any) -> None:
        self.users[user.telegram_user_id] = user


@pytest.fixture
async def bot() -> AsyncGenerator[tuple[Bot, RecordingSession], None]:
    session = RecordingSession()
    instance = Bot("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session)
    yield instance, session
    await instance.session.close()


def _start(payload: str | None, user_id: int = 42) -> Update:
    text = "/start" if payload is None else f"/start {payload}"
    user = TelegramUser(id=user_id, is_bot=False, first_name="Анна", username="anna")
    return Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=user,
            text=text,
            entities=[MessageEntity(type="bot_command", offset=0, length=6)],
        ),
    )


async def test_the_command_menu_and_its_button_are_published_together(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot

    await configure_commands(instance)

    kinds = [type(method).__name__ for method in session.methods]
    assert kinds == ["SetMyCommands", "SetChatMenuButton"]
    published = session.methods[0]
    assert isinstance(published, SetMyCommands)
    assert [command.command for command in published.commands] == [
        command.command for command in BOT_COMMANDS
    ]
    assert isinstance(session.methods[1], SetChatMenuButton)


async def test_every_published_command_explains_itself(
    bot: tuple[Bot, RecordingSession],
) -> None:
    assert all(command.description.strip() for command in BOT_COMMANDS)
    assert len({command.command for command in BOT_COMMANDS}) == len(BOT_COMMANDS)


async def test_telegram_refusing_the_command_list_does_not_stop_the_bot(
    bot: tuple[Bot, RecordingSession],
) -> None:
    """A cosmetic call must never turn a transient network error into a failed boot."""

    instance, session = bot
    session.refuse = TelegramBadRequest(
        method=SetMyCommands(commands=[]), message="Bad Request: too many requests"
    )

    await configure_commands(instance)

    assert len(session.methods) == 1


async def test_boot_seeds_the_persona_registry_and_publishes_the_menu(
    bot: tuple[Bot, RecordingSession],
) -> None:
    """Personas are seeded by the process that serves readings, not by an aiogram hook.

    Production feeds updates straight into the dispatcher and never emits `startup`, so a
    registry synced only from that hook stays empty on the server and every reading fails
    with `PersonaUnavailableError`.
    """

    instance, session = bot
    registry = RecordingPersonaRegistry()

    await prepare_runtime(instance, cast("PersonaRegistryService", registry))

    assert registry.syncs == 1
    assert [type(method).__name__ for method in session.methods] == [
        "SetMyCommands",
        "SetChatMenuButton",
    ]


def test_neither_entry_point_relies_on_the_startup_event() -> None:
    """A hook registered on `dispatcher.startup` runs locally and never on the server."""

    sources = (
        Path(inspect.getfile(app_main)).read_text(),
        Path(inspect.getfile(telegram_worker)).read_text(),
    )
    assert all("dispatcher.startup.register" not in source for source in sources)
    assert all("prepare_runtime" in source for source in sources)


async def test_a_deep_link_lands_on_the_scenario_it_promised(
    bot: tuple[Bot, RecordingSession],
) -> None:
    instance, session = bot
    dispatcher = Dispatcher()
    dispatcher.include_router(create_persona_router(TAROT_FLOW))
    service = OnboardingService(MemoryUsers(), NoOpAnalytics())
    await service.start(TelegramIdentity(42, "anna", "Анна", "ru"))
    await service.accept_consent(42)

    await dispatcher.feed_update(
        instance,
        _start(TAROT_FLOW.namespace),
        onboarding=service,
        privacy_retention_days=RETENTION_DAYS,
    )

    assert shown_texts(session.methods)[-1] == TAROT_FLOW.texts.welcome


async def test_an_unknown_payload_is_ignored_rather_than_followed(
    bot: tuple[Bot, RecordingSession],
) -> None:
    """The payload arrives from outside; only an exact scenario code selects a handler."""

    instance, session = bot
    dispatcher = Dispatcher()
    dispatcher.include_router(create_persona_router(TAROT_FLOW))
    service = OnboardingService(MemoryUsers(), NoOpAnalytics())
    await service.start(TelegramIdentity(42, "anna", "Анна", "ru"))
    await service.accept_consent(42)

    await dispatcher.feed_update(
        instance,
        _start("tarot; drop table readings"),
        onboarding=service,
        privacy_retention_days=RETENTION_DAYS,
    )

    assert session.methods == []
