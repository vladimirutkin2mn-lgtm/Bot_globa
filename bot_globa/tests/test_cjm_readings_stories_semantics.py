import inspect

from app.bot.keyboards import main_menu_keyboard
from app.bot.persona_flow import ADD_TO_STORY_BUTTON
from app.bot.reading_renderer import render_full
from app.bot.reading_story_continuation_handlers import _NEW_SESSION_PROMPT
from app.bot.reading_story_keyboards import story_all_readings_keyboard


def _labels(keyboard):
    return [button.text for row in keyboard.inline_keyboard for button in row]


def test_primary_history_object_is_a_reading_and_story_is_an_optional_group() -> None:
    assert "📚 Мои разборы" in _labels(main_menu_keyboard())
    assert ADD_TO_STORY_BUTTON == "＋ Добавить к истории"
    assert "← К моим разборам" in _labels(story_all_readings_keyboard())
    assert "🌙 Внутренний разбор" in _labels(story_all_readings_keyboard())


def test_full_result_and_new_story_session_use_the_same_semantics() -> None:
    assert "Моих разборах" in inspect.getsource(render_full)
    assert "новый отдельный разбор" in _NEW_SESSION_PROMPT
    assert "добавить к этой истории" in _NEW_SESSION_PROMPT
    assert "память используется" not in _NEW_SESSION_PROMPT.casefold()
