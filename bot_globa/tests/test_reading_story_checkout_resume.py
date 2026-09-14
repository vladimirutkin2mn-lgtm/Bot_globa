"""A story-started reading keeps its selected story across checkout and payment."""

import inspect
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import chat_scope_handlers
from app.bot.keyboards import payment_success_keyboard, reading_resume_callback
from app.bot.reading_story_context import (
    direct_story_link_callback,
    target_story_keyboard,
)
from app.domain.reading_checkout_resume import (
    ReadingCheckoutTarget,
    parse_reading_resume_callback,
    reading_target_from_snapshot,
)

_READING_ID = UUID("11111111-2222-3333-4444-555555555555")
_STORY_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_PERSONAS = {
    "tarot_reader": "tarot",
    "love_oracle": "love",
    "mystical_psychologist": "psy",
    "astrologer": "astro",
}


def _callbacks(markup: InlineKeyboardMarkup) -> list[str]:
    return [
        callback
        for row in markup.inline_keyboard
        for button in row
        if (callback := button.callback_data) is not None
    ]


def test_legacy_reading_checkout_callbacks_are_byte_for_byte_unchanged() -> None:
    for persona_code, route in _PERSONAS.items():
        target = ReadingCheckoutTarget(_READING_ID, persona_code)

        assert target.callback_data == f"{route}:unlock:{_READING_ID}"
        assert parse_reading_resume_callback(target.callback_data) == target
        assert target.snapshot() == {
            "kind": "reading",
            "reading_id": str(_READING_ID),
            "persona_code": persona_code,
        }


def test_story_checkout_target_round_trips_through_callback_snapshot_and_payment_success() -> None:
    for persona_code, route in _PERSONAS.items():
        target = ReadingCheckoutTarget(_READING_ID, persona_code, _STORY_ID)

        assert target.callback_data.startswith(f"{route}:unlock:")
        assert len(target.callback_data.encode("utf-8")) <= 64
        assert parse_reading_resume_callback(target.callback_data) == target
        assert reading_target_from_snapshot({"resume_target": target.snapshot()}) == target

        payment = payment_success_keyboard(target.callback_data)
        assert target.callback_data in _callbacks(payment)


def test_legacy_snapshot_still_decodes_without_story_context() -> None:
    snapshot: dict[str, object] = {
        "resume_target": {
            "kind": "reading",
            "reading_id": str(_READING_ID),
            "persona_code": "tarot_reader",
        }
    }

    assert reading_target_from_snapshot(snapshot) == ReadingCheckoutTarget(
        _READING_ID,
        "tarot_reader",
    )


def test_story_result_keyboard_targets_both_save_and_unlock_actions() -> None:
    generic_unlock = f"tarot:unlock:{_READING_ID}"
    generic_save = f"stories:link:{_READING_ID}"
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть полностью", callback_data=generic_unlock)],
            [InlineKeyboardButton(text="＋ Добавить в историю", callback_data=generic_save)],
            [InlineKeyboardButton(text="Меню", callback_data="menu:home")],
        ]
    )

    targeted = target_story_keyboard(markup, _STORY_ID, _READING_ID)
    callbacks = _callbacks(targeted)
    durable = ReadingCheckoutTarget(_READING_ID, "tarot_reader", _STORY_ID).callback_data

    assert durable in callbacks
    assert direct_story_link_callback(_STORY_ID, _READING_ID) in callbacks
    assert generic_unlock not in callbacks
    assert generic_save not in callbacks
    assert "menu:home" in callbacks
    assert reading_resume_callback(targeted) == durable


def test_story_targeting_does_not_change_a_regular_result_keyboard() -> None:
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть полностью",
                    callback_data=f"tarot:unlock:{_READING_ID}",
                )
            ]
        ]
    )

    assert target_story_keyboard(markup, None, _READING_ID) is markup


def test_story_checkout_parser_rejects_malformed_or_mixed_targets() -> None:
    assert parse_reading_resume_callback(None) is None
    assert parse_reading_resume_callback("tarot:unlock:broken") is None
    assert parse_reading_resume_callback("tarot:unlock:broken:broken") is None
    assert parse_reading_resume_callback(f"unknown:unlock:{_READING_ID}") is None
    assert (
        reading_target_from_snapshot(
            {
                "resume_target": {
                    "kind": "reading",
                    "reading_id": str(_READING_ID),
                    "persona_code": "tarot_reader",
                    "story_id": "broken",
                }
            }
        )
        is None
    )


def test_story_checkout_router_is_nested_before_persona_routers() -> None:
    source = inspect.getsource(chat_scope_handlers)

    assert "router.include_router(reading_story_checkout_router)" in source
