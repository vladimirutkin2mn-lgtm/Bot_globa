from datetime import UTC, datetime
from uuid import UUID

from app.bot.reading_story_keyboards import StoryReadingButton, stories_hub_keyboard
from app.domain.reading_story import ReadingStoryView


def test_stories_hub_prioritizes_recent_readings_and_marks_active_followup() -> None:
    now = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    active_reading = StoryReadingButton(
        reading_id=UUID(int=1),
        label="🔮 Отношения · 13.09.2026",
        open_callback="tarot:history:open:00000000-0000-0000-0000-000000000001",
        active_followup=True,
    )
    inactive_reading = StoryReadingButton(
        reading_id=UUID(int=2),
        label="🌙 Карьера · 12.09.2026",
        open_callback="psy:history:open:00000000-0000-0000-0000-000000000002",
    )
    story = ReadingStoryView(
        id=UUID(int=3),
        title="Новая работа",
        reading_ids=(),
        created_at=now,
        updated_at=now,
    )

    keyboard = stories_hub_keyboard(
        (story,),
        recent_readings=(active_reading, inactive_reading),
    )
    rows = keyboard.inline_keyboard

    assert rows[0][0].text == "🟢 🔮 Отношения · 13.09.2026"
    assert rows[0][0].callback_data == active_reading.open_callback
    assert rows[1][0].text == "🌙 Карьера · 12.09.2026"
    assert rows[1][0].callback_data == inactive_reading.open_callback
    assert rows[2][0].text == "📖 Новая работа"
    assert rows[2][0].callback_data == f"stories:open:{story.id}:0"
    assert rows[-3][0].callback_data == "stories:create"
    assert rows[-2][0].callback_data == "stories:all"
    assert rows[-1][0].callback_data == "menu:home"
