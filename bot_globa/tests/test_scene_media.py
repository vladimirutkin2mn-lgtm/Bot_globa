"""CJM scene assets and the shared Telegram sender stay in sync."""

from typing import cast
from unittest.mock import AsyncMock, Mock

from aiogram.types import Message

from app.bot.scene_media import TELEGRAM_CAPTION_LIMIT, Scene, answer_scene


def test_every_current_cjm_scene_has_one_optimized_asset() -> None:
    assets = {path.stem for path in Scene.ONBOARDING_START.asset_path.parent.glob("*.jpg")}

    assert assets == {scene.value for scene in Scene}
    assert "O-02" not in assets
    assert all(scene.asset_path.stat().st_size < 1_000_000 for scene in Scene)


async def test_short_scene_copy_is_sent_as_one_photo_caption() -> None:
    message = Mock(spec=Message)
    message.answer_photo = AsyncMock(return_value=object())
    message.answer = AsyncMock()

    await answer_scene(cast("Message", message), Scene.MAIN_MENU, "Главное меню")

    message.answer_photo.assert_awaited_once()
    assert message.answer_photo.await_args.kwargs["caption"] == "Главное меню"
    message.answer.assert_not_awaited()


async def test_long_scene_copy_keeps_the_photo_and_full_text() -> None:
    message = Mock(spec=Message)
    message.answer_photo = AsyncMock(return_value=object())
    message.answer = AsyncMock(return_value=object())
    text = "д" * (TELEGRAM_CAPTION_LIMIT + 1)

    await answer_scene(cast("Message", message), Scene.PRIVACY, text)

    message.answer_photo.assert_awaited_once()
    assert "caption" not in message.answer_photo.await_args.kwargs
    message.answer.assert_awaited_once_with(text, reply_markup=None)
