"""Direct save-to-story buttons stay available and Telegram-safe."""

import inspect
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import main as bot_main
from app.bot.horoscope_flow import HOROSCOPE_FLOW
from app.bot.persona_flow import ADD_TO_STORY_BUTTON
from app.bot.persona_flows import LOVE_ORACLE_FLOW, MYSTICAL_PSYCHOLOGIST_FLOW, TAROT_FLOW
from app.bot.reading_story_context import (
    STORY_CONTINUATION_ID_KEY,
    continuation_story_id,
    direct_story_link_callback,
    parse_direct_story_link,
    target_story_keyboard,
)

_READING_ID = UUID("11111111-2222-3333-4444-555555555555")
_STORY_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_FLOWS = (TAROT_FLOW, LOVE_ORACLE_FLOW, MYSTICAL_PSYCHOLOGIST_FLOW, HOROSCOPE_FLOW)
_EXPECTED_CALLBACK = f"stories:link:{_READING_ID}"


def _buttons(markup: InlineKeyboardMarkup) -> list[InlineKeyboardButton]:
    return [button for row in markup.inline_keyboard for button in row]


def test_every_personal_flow_offers_direct_story_save() -> None:
    for flow in _FLOWS:
        for markup in (
            flow.result_keyboard(_READING_ID, 40),
            flow.full_result_keyboard(_READING_ID),
        ):
            buttons = _buttons(markup)
            direct = [button for button in buttons if button.text == ADD_TO_STORY_BUTTON]
            assert len(direct) == 1
            assert direct[0].callback_data == _EXPECTED_CALLBACK
            assert len(_EXPECTED_CALLBACK.encode()) <= 64


def test_continuation_result_can_target_the_selected_story_in_one_click() -> None:
    callback = direct_story_link_callback(_STORY_ID, _READING_ID)

    assert parse_direct_story_link(callback) == (_STORY_ID, _READING_ID)
    assert len(callback.encode()) <= 64
    assert continuation_story_id({STORY_CONTINUATION_ID_KEY: str(_STORY_ID)}) == _STORY_ID

    for flow in _FLOWS:
        targeted = target_story_keyboard(
            flow.result_keyboard(_READING_ID, 40),
            _STORY_ID,
            _READING_ID,
        )
        buttons = _buttons(targeted)
        direct = [button for button in buttons if button.text == "＋ Добавить в эту историю"]
        assert len(direct) == 1
        assert direct[0].callback_data == callback
        assert _EXPECTED_CALLBACK not in [button.callback_data for button in buttons]


def test_targeted_story_callback_parser_rejects_malformed_payloads() -> None:
    assert parse_direct_story_link(None) is None
    assert parse_direct_story_link("stories:here:broken") is None
    assert parse_direct_story_link("stories:here:" + "я" * 22 + ":" + "x" * 22) is None
    assert continuation_story_id({STORY_CONTINUATION_ID_KEY: "broken"}) is None


def test_targeting_is_noop_outside_story_continuation() -> None:
    generic = TAROT_FLOW.full_result_keyboard(_READING_ID)
    assert target_story_keyboard(generic, None, _READING_ID) is generic


def test_direct_story_router_is_live_before_legacy_core_router() -> None:
    source = inspect.getsource(bot_main.create_dispatcher)
    link_registration = "dispatcher.include_router(reading_story_link_router)"
    legacy_registration = "dispatcher.include_router(core_router)"

    assert link_registration in source
    assert source.index(link_registration) < source.index(legacy_registration)
