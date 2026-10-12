from app.prompts.daily_horoscope import DAILY_HOROSCOPE_PROMPT_VERSION


def test_daily_editor_has_one_versioned_shared_prompt() -> None:
    assert DAILY_HOROSCOPE_PROMPT_VERSION.startswith("daily-editor-")
