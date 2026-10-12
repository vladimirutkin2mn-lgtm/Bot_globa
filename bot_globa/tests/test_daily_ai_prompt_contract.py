from app.prompts.daily_horoscope import (
    DAILY_HOROSCOPE_PROMPT_VERSION,
    DAILY_HOROSCOPE_SYSTEM_PROMPT,
)


def test_daily_editor_is_grounded_and_history_aware() -> None:
    assert DAILY_HOROSCOPE_PROMPT_VERSION == "daily-editor-v1"
    lowered = DAILY_HOROSCOPE_SYSTEM_PROMPT.casefold()
    assert "do not recalculate" in lowered
    assert "recent_history" in lowered
    assert "do not reuse" in lowered
