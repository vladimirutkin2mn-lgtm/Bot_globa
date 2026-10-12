from app.domain.persona import persona_definition
from app.prompts.horoscope import load_horoscope_prompts
from app.prompts.oracle import load_oracle_reading_prompts
from app.prompts.reading import load_reading_prompts


def test_current_personas_point_to_new_editorial_prompt_versions() -> None:
    expected = {
        "tarot_reader": "tarot-reader-v5",
        "love_oracle": "love-oracle-v3",
        "mystical_psychologist": "mystical-psychologist-v3",
        "astrologer": "astrologer-v3",
    }
    for code, prompt_version in expected.items():
        definition = persona_definition(code)
        assert definition is not None
        assert definition.prompt_version == prompt_version


def test_previous_prompt_versions_remain_resolvable() -> None:
    assert load_oracle_reading_prompts("tarot-reader-v4")
    assert load_oracle_reading_prompts("mystical-psychologist-v2")
    assert load_reading_prompts("love-oracle-v2")
    assert load_horoscope_prompts("astrologer-v2")
