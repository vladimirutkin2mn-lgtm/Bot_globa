"""Fast contracts for continuing a manual reading story."""

from uuid import uuid4

from aiogram.types import InlineKeyboardMarkup

from app.bot.horoscope_flow import HOROSCOPE_FLOW
from app.bot.persona_flows import LOVE_ORACLE_FLOW, MYSTICAL_PSYCHOLOGIST_FLOW, TAROT_FLOW
from app.bot.reading_story_continuation_handlers import (
    _CONTINUATION_FLOWS,
    _NEW_SESSION_PROMPT,
    _has_included_followup,
    _parse_uuid,
)
from app.bot.reading_story_keyboards import (
    StoryReadingButton,
    story_astrology_profile_keyboard,
    story_continuation_cancel_keyboard,
    story_detail_keyboard,
)
from app.services.reading_followup import ReadingFollowUpStatus


def _callbacks(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [
        callback
        for row in keyboard.inline_keyboard
        for button in row
        if (callback := button.callback_data) is not None
    ]


def test_included_followup_requires_live_remaining_question() -> None:
    for status in (
        ReadingFollowUpStatus.READY,
        ReadingFollowUpStatus.COMPLETED,
        ReadingFollowUpStatus.CORRUPTED_HISTORY,
    ):
        assert _has_included_followup(status, 1) is True
        assert _has_included_followup(status, 0) is False

    for status in (
        ReadingFollowUpStatus.EXPIRED,
        ReadingFollowUpStatus.NOT_ELIGIBLE,
        ReadingFollowUpStatus.PROCESSING,
    ):
        assert _has_included_followup(status, 2) is False


def test_current_personas_continue_through_their_existing_question_states() -> None:
    expected = {
        TAROT_FLOW.persona_code: TAROT_FLOW.states.waiting_for_question,
        LOVE_ORACLE_FLOW.persona_code: LOVE_ORACLE_FLOW.states.waiting_for_question,
        MYSTICAL_PSYCHOLOGIST_FLOW.persona_code: (
            MYSTICAL_PSYCHOLOGIST_FLOW.states.waiting_for_question
        ),
        HOROSCOPE_FLOW.persona_code: HOROSCOPE_FLOW.states.waiting_for_question,
    }
    assert {code: flow.question_state for code, flow in _CONTINUATION_FLOWS.items()} == expected


def test_new_story_session_copy_is_explicit_about_separate_access_and_memory() -> None:
    assert "новый отдельный разбор" in _NEW_SESSION_PROMPT
    assert "расходуется отдельно" in _NEW_SESSION_PROMPT
    assert "Старые тексты из истории" in _NEW_SESSION_PROMPT
    assert "память используется только если вы уже включили" in _NEW_SESSION_PROMPT
    assert "prompt" not in _NEW_SESSION_PROMPT.casefold()


def test_story_continuation_callbacks_fit_telegram_limit() -> None:
    story_id = uuid4()
    reading_id = uuid4()
    detail = story_detail_keyboard(
        story_id,
        (
            StoryReadingButton(
                reading_id,
                "🔮 Выбор · 11.09.2026",
                f"tarot:history:open:{reading_id}",
            ),
        ),
        page=0,
        has_next=False,
    )
    callbacks = _callbacks(detail)
    assert f"stories:continue:{story_id}" in callbacks

    for keyboard in (
        detail,
        story_continuation_cancel_keyboard(story_id),
        story_astrology_profile_keyboard(story_id),
    ):
        assert all(len(callback.encode("utf-8")) <= 64 for callback in _callbacks(keyboard))


def test_story_continuation_uuid_parser_is_strict_to_prefix_and_uuid() -> None:
    story_id = uuid4()
    assert _parse_uuid(f"stories:continue:{story_id}", "stories:continue:") == story_id
    assert _parse_uuid("stories:continue:not-a-uuid", "stories:continue:") is None
    assert _parse_uuid(f"wrong:{story_id}", "stories:continue:") is None
