from app.prompts.reading_followup import (
    DEFAULT_READING_FOLLOWUP_PROMPT_VERSION,
    KNOWN_READING_FOLLOWUP_PROMPT_VERSIONS,
)


def test_followup_prompt_v2_is_registered() -> None:
    assert DEFAULT_READING_FOLLOWUP_PROMPT_VERSION == "reading_followup_v2"
    assert "reading_followup_v1" in KNOWN_READING_FOLLOWUP_PROMPT_VERSIONS
    assert "reading_followup_v2" in KNOWN_READING_FOLLOWUP_PROMPT_VERSIONS
