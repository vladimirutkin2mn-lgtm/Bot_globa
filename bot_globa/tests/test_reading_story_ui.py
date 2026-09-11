"""Fast contracts for the manual reading-story Telegram UI."""

from datetime import UTC, datetime
from uuid import uuid4

from aiogram.types import InlineKeyboardMarkup

from app.bot.reading_story_handlers import _parse_story_page, _reading_button
from app.bot.reading_story_keyboards import (
    StoryReadingButton,
    stories_hub_keyboard,
    story_add_readings_keyboard,
    story_delete_confirmation_keyboard,
    story_detail_keyboard,
)
from app.domain.reading_history import ReadingHistoryChoice
from app.domain.reading_story import ReadingStoryView


def _callbacks(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [
        callback
        for row in keyboard.inline_keyboard
        for button in row
        if (callback := button.callback_data) is not None
    ]


def test_story_callbacks_keep_private_titles_out_and_fit_telegram_limit() -> None:
    story_id = uuid4()
    secret = "Очень личное название истории про отношения"
    story = ReadingStoryView(
        id=story_id,
        title=secret,
        reading_ids=(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    hub = stories_hub_keyboard((story,))
    callbacks = _callbacks(hub)

    assert f"stories:open:{story_id}:0" in callbacks
    assert all(secret not in callback for callback in callbacks)
    assert all(len(callback.encode("utf-8")) <= 64 for callback in callbacks)

    reading = StoryReadingButton(uuid4(), "🔮 Выбор · 11.09.2026", f"tarot:history:open:{uuid4()}")
    keyboards = (
        story_detail_keyboard(story_id, (reading,), page=12, has_next=True),
        story_add_readings_keyboard(story_id, (reading,), page=12, has_next=True),
        story_delete_confirmation_keyboard(story_id),
    )
    for keyboard in keyboards:
        assert all(len(callback.encode("utf-8")) <= 64 for callback in _callbacks(keyboard))


def test_story_reading_buttons_reuse_existing_persona_history_routes() -> None:
    cases = (
        ("tarot_reader", "work", "tarot:history:open:"),
        ("love_oracle", "communication", "love:history:open:"),
        ("mystical_psychologist", "decision", "psy:history:open:"),
        ("astrologer", "week_forecast", "astro:history:open:"),
    )
    for persona_code, topic, prefix in cases:
        reading_id = uuid4()
        item = ReadingHistoryChoice(
            reading_id=reading_id,
            persona_code=persona_code,
            topic=topic,
            status="preview_ready",
            created_at=datetime(2026, 9, 11, tzinfo=UTC),
        )
        button = _reading_button(item)
        assert button.reading_id == reading_id
        assert button.open_callback == f"{prefix}{reading_id}"
        assert "11.09.2026" in button.label


def test_unknown_legacy_persona_never_invents_a_renderer_route() -> None:
    reading_id = uuid4()
    button = _reading_button(
        ReadingHistoryChoice(
            reading_id=reading_id,
            persona_code="legacy_unknown",
            topic="decision",
            status="preview_ready",
            created_at=datetime.now(UTC),
        )
    )
    assert button.open_callback == f"stories:unavailable:{reading_id}"


def test_story_page_parser_rejects_malformed_payloads_and_clamps_negative_page() -> None:
    story_id = uuid4()
    assert _parse_story_page(f"stories:open:{story_id}:3", "stories:open:") == (story_id, 3)
    assert _parse_story_page(f"stories:open:{story_id}:-4", "stories:open:") == (story_id, 0)
    assert _parse_story_page("stories:open:not-a-uuid:1", "stories:open:") is None
    assert _parse_story_page(f"wrong:{story_id}:1", "stories:open:") is None
