"""CJM scene assets and the shared Telegram sender stay in sync."""

from collections.abc import Iterator
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendPhoto
from aiogram.types import InlineKeyboardMarkup, Message, PhotoSize
from aiogram.types.input_file import FSInputFile

from app.bot import scene_media
from app.bot.scene_media import TELEGRAM_CAPTION_LIMIT, Scene, answer_scene


@pytest.fixture(autouse=True)
def _clean_file_id_cache() -> Iterator[None]:
    scene_media._telegram_file_ids.clear()
    yield
    scene_media._telegram_file_ids.clear()


def _refused() -> TelegramBadRequest:
    return TelegramBadRequest(method=SendPhoto(chat_id=1, photo="x"), message="wrong file id")


def _photo_message(file_id: str) -> Mock:
    sent = Mock(spec=Message)
    sent.photo = [PhotoSize(file_id=file_id, file_unique_id="u", width=1, height=1)]
    return sent


def test_every_current_cjm_scene_has_one_optimized_asset() -> None:
    assets = {path.stem for path in Scene.ONBOARDING_START.asset_path.parent.glob("*.jpg")}

    assert assets == {scene.value for scene in Scene}
    assert "O-02" not in assets
    assert all(scene.asset_path.stat().st_size < 1_000_000 for scene in Scene)


async def test_hero_scene_copy_is_sent_as_one_photo_caption() -> None:
    message = Mock(spec=Message)
    message.answer_photo = AsyncMock(return_value=object())
    message.answer = AsyncMock()

    await answer_scene(cast("Message", message), Scene.TAROT_ENTRY, "Выберите тему")

    message.answer_photo.assert_awaited_once()
    assert message.answer_photo.await_args.kwargs["caption"] == "Выберите тему"
    message.answer.assert_not_awaited()


async def test_long_hero_copy_keeps_the_photo_and_full_text() -> None:
    message = Mock(spec=Message)
    message.answer_photo = AsyncMock(return_value=object())
    message.answer = AsyncMock(return_value=object())
    text = "д" * (TELEGRAM_CAPTION_LIMIT + 1)

    await answer_scene(cast("Message", message), Scene.FULL_READING, text)

    message.answer_photo.assert_awaited_once()
    assert "caption" not in message.answer_photo.await_args.kwargs
    message.answer.assert_awaited_once_with(text, reply_markup=None)


async def test_utility_scene_is_plain_text_without_decorative_media() -> None:
    message = Mock(spec=Message)
    message.answer_photo = AsyncMock(return_value=object())
    message.answer = AsyncMock(return_value=object())

    await answer_scene(cast("Message", message), Scene.PRIVACY, "Приватность")

    message.answer_photo.assert_not_awaited()
    message.answer.assert_awaited_once_with("Приватность", reply_markup=None)


async def test_a_refused_photo_still_delivers_the_copy_as_text() -> None:
    message = Mock(spec=Message)
    message.answer_photo = AsyncMock(side_effect=_refused())
    message.answer = AsyncMock(return_value=object())
    markup = InlineKeyboardMarkup(inline_keyboard=[])

    await answer_scene(cast("Message", message), Scene.PREVIEW, "Превью", reply_markup=markup)

    message.answer.assert_awaited_once_with("Превью", reply_markup=markup)


async def test_the_second_send_reuses_the_cached_file_id() -> None:
    message = Mock(spec=Message)
    message.answer_photo = AsyncMock(return_value=_photo_message("cached-id"))
    message.answer = AsyncMock()

    await answer_scene(cast("Message", message), Scene.GENERATING, "Собираю разбор")
    await answer_scene(cast("Message", message), Scene.GENERATING, "Собираю разбор")

    assert message.answer_photo.await_args.kwargs["photo"] == "cached-id"
    message.answer.assert_not_awaited()


async def test_a_rejected_cached_file_id_is_dropped_and_the_asset_re_uploaded() -> None:
    message = Mock(spec=Message)
    message.answer_photo = AsyncMock(return_value=_photo_message("stale-id"))
    message.answer = AsyncMock()
    await answer_scene(cast("Message", message), Scene.PREVIEW, "Превью")

    message.answer_photo = AsyncMock(
        side_effect=[_refused(), _photo_message("fresh-id")],
    )
    await answer_scene(cast("Message", message), Scene.PREVIEW, "Превью")

    assert message.answer_photo.await_count == 2
    assert message.answer_photo.await_args_list[0].kwargs["photo"] == "stale-id"
    assert isinstance(message.answer_photo.await_args_list[1].kwargs["photo"], FSInputFile)
    assert scene_media._telegram_file_ids[Scene.PREVIEW] == "fresh-id"
    message.answer.assert_not_awaited()
