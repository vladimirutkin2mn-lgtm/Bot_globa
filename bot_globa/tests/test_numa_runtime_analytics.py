"""Runtime source-attribution tests without Telegram, database or LLM I/O."""

from datetime import UTC, datetime
from uuid import uuid4

from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot.numa_runtime_analytics import runtime_entity_id, runtime_signal
from app.providers.numa_product_analytics import ProductFlow, ProductSource


def _user() -> User:
    return User(id=123456, is_bot=False, first_name="Test")


def test_daily_cta_is_attributed_to_daily_horoscope() -> None:
    callback = CallbackQuery(
        id="callback-1",
        from_user=_user(),
        chat_instance="chat-instance",
        data="daily:personal",
    )
    signal = runtime_signal(Update(update_id=1001, callback_query=callback))

    assert signal is not None
    assert signal.attribution.flow is ProductFlow.PERSONAL
    assert signal.attribution.source is ProductSource.DAILY_HOROSCOPE
    assert signal.attribution.scenario_version == "personal_day_forecast_v1"


def test_group_command_keeps_specific_mechanic_source() -> None:
    message = Message(
        message_id=5,
        date=datetime.now(UTC),
        chat=Chat(id=-100123, type=ChatType.SUPERGROUP),
        from_user=_user(),
        text="/compatibility@numa_bot",
    )
    signal = runtime_signal(Update(update_id=1002, message=message))

    assert signal is not None
    assert signal.attribution.flow is ProductFlow.GROUP
    assert signal.attribution.source is ProductSource.GROUP_COMPATIBILITY


def test_personal_menu_entry_is_normal_start() -> None:
    callback = CallbackQuery(
        id="callback-2",
        from_user=_user(),
        chat_instance="chat-instance",
        data="oracle:love",
    )
    signal = runtime_signal(Update(update_id=1003, callback_query=callback))

    assert signal is not None
    assert signal.attribution.flow is ProductFlow.PERSONAL
    assert signal.attribution.source is ProductSource.NORMAL_START
    assert signal.attribution.scenario_version == "love_oracle_v1"


def test_retry_of_same_update_has_same_opaque_entity_id() -> None:
    callback = CallbackQuery(
        id="callback-3",
        from_user=_user(),
        chat_instance="chat-instance",
        data="oracle:auto",
    )
    signal = runtime_signal(Update(update_id=1004, callback_query=callback))
    assert signal is not None
    internal_user_id = uuid4()

    first = runtime_entity_id(signal, internal_user_id)
    second = runtime_entity_id(signal, internal_user_id)

    assert first == second
    assert "1004" not in str(first)


def test_ordinary_private_message_is_not_analytics_entry() -> None:
    message = Message(
        message_id=6,
        date=datetime.now(UTC),
        chat=Chat(id=42, type=ChatType.PRIVATE),
        from_user=_user(),
        text="private question that must never enter analytics",
    )

    assert runtime_signal(Update(update_id=1005, message=message)) is None
