from app.prompts.reading_followup import (
    DEFAULT_READING_FOLLOWUP_PROMPT_VERSION,
    load_reading_followup_prompts,
)


def test_followup_v2_is_registered_as_current_prompt_pack() -> None:
    prompts = load_reading_followup_prompts(DEFAULT_READING_FOLLOWUP_PROMPT_VERSION)

    assert prompts.version == "reading_followup_v2"
    assert "не пересказывай весь разбор" in prompts.system.casefold()
    assert "не добавляют новой информации" in prompts.request.casefold()
