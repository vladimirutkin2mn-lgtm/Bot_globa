from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from pydantic import SecretStr

from app.bot.main import configure_webhook
from app.bot.reading_feedback_handlers import router as reading_feedback_router
from app.config import Settings
from app.providers.numa_product_analytics import ProductFunnelEvent, is_numa_product_event


def _settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+asyncpg://u:p@db/x",
        telegram_bot_token=SecretStr("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        telegram_webhook_url="https://numa.example/telegram/webhook",
        telegram_webhook_secret=SecretStr("webhook-secret"),
        content_encryption_key=SecretStr("daily-share-selected-test-key"),
    )


def test_share_selected_is_a_typed_numa_product_event() -> None:
    assert ProductFunnelEvent.SHARE_SELECTED.value == "numa_share_selected"
    assert is_numa_product_event(ProductFunnelEvent.SHARE_SELECTED.value)
    assert "chosen_inline_result" in reading_feedback_router.resolve_used_update_types()


@pytest.mark.asyncio
async def test_webhook_requests_chosen_inline_result_updates() -> None:
    bot = AsyncMock(spec=Bot)

    await configure_webhook(bot, _settings())

    bot.set_webhook.assert_awaited_once()
    allowed = bot.set_webhook.await_args.kwargs["allowed_updates"]
    assert "inline_query" in allowed
    assert "chosen_inline_result" in allowed
