"""Story-started 24-hour follow-ups keep their story navigation."""

from uuid import UUID

from app.bot.persona_flow import FOLLOWUP_NAMESPACE
from app.bot.reading_followup_handlers import (
    _cancel_keyboard,
    _followup_result_keyboard,
    _retry_keyboard,
    _return_keyboard,
)

_READING_ID = UUID("11111111-2222-3333-4444-555555555555")
_STORY_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _callbacks(markup: object) -> list[str]:
    keyboard = markup.inline_keyboard  # type: ignore[attr-defined]
    return [
        callback
        for row in keyboard
        for button in row
        if (callback := button.callback_data) is not None
    ]


def test_story_followup_keeps_next_question_and_back_navigation_in_story() -> None:
    callbacks = _callbacks(
        _followup_result_keyboard(
            _READING_ID,
            2,
            subscriptions_enabled=False,
            story_id=_STORY_ID,
        )
    )

    assert f"stories:continue:{_STORY_ID}" in callbacks
    assert f"stories:open:{_STORY_ID}:0" in callbacks
    assert f"{FOLLOWUP_NAMESPACE}:ask:{_READING_ID}" not in callbacks
    assert all(len(callback.encode()) <= 64 for callback in callbacks)


def test_story_followup_cancel_retry_and_terminal_return_stay_in_story() -> None:
    for keyboard in (
        _cancel_keyboard(_STORY_ID),
        _retry_keyboard(_READING_ID, _STORY_ID),
        _return_keyboard(_STORY_ID),
    ):
        callbacks = _callbacks(keyboard)
        assert any(callback.startswith("stories:") for callback in callbacks)
        assert all(len(callback.encode()) <= 64 for callback in callbacks)


def test_regular_followup_keeps_existing_generic_navigation() -> None:
    callbacks = _callbacks(
        _followup_result_keyboard(
            _READING_ID,
            1,
            subscriptions_enabled=False,
        )
    )

    assert f"{FOLLOWUP_NAMESPACE}:ask:{_READING_ID}" in callbacks
    assert all(not callback.startswith("stories:") for callback in callbacks)
