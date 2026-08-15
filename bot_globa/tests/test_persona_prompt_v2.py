"""Product contracts for the differentiated Russian persona prompt generation."""

from app.bot.persona_flows import LOVE_ORACLE_FLOW, MYSTICAL_PSYCHOLOGIST_FLOW, TAROT_FLOW
from app.domain.persona import persona_definition
from app.prompts.horoscope import load_horoscope_prompts
from app.prompts.oracle import load_oracle_reading_prompts


def test_active_personas_use_the_new_prompt_versions() -> None:
    expected = {
        "tarot_reader": "tarot-reader-v4",
        "love_oracle": "love-oracle-v2",
        "mystical_psychologist": "mystical-psychologist-v2",
        "astrologer": "astrologer-v2",
    }

    assert {
        code: persona_definition(code).prompt_version  # type: ignore[union-attr]
        for code in expected
    } == expected


def test_every_active_persona_requires_russian_user_facing_prose() -> None:
    systems = (
        load_oracle_reading_prompts("tarot-reader-v4").system,
        load_oracle_reading_prompts("love-oracle-v2").system,
        load_oracle_reading_prompts("mystical-psychologist-v2").system,
        load_horoscope_prompts("astrologer-v2").system,
    )

    for system in systems:
        assert "natural Russian" in system
        assert "never output" in system


def test_tarot_v4_is_rws_bound_and_does_not_outsource_card_knowledge_to_the_llm() -> None:
    prompt = load_oracle_reading_prompts("tarot-reader-v4")

    assert "Rider-Waite-Smith" in prompt.system
    assert "application-owned card knowledge" in prompt.system
    assert "orientation_meaning" in prompt.system
    assert "position_focus" in prompt.system
    assert "Never invent a different card meaning" in prompt.system
    assert "one spread, not three unrelated card definitions" in prompt.system
    assert "synthesize at least two cards" in prompt.request_instruction


def test_love_oracle_answers_without_claiming_private_mind_reading() -> None:
    prompt = load_oracle_reading_prompts("love-oracle-v2").system

    assert "Answer the emotional question immediately" in prompt
    assert "do not dodge the question" in prompt
    assert "private thoughts, feelings, intentions" in prompt
    assert "as known facts" in prompt


def test_mystical_psychologist_is_metaphorical_not_clinical() -> None:
    prompt = load_oracle_reading_prompts("mystical-psychologist-v2").system

    assert "different from both a therapist and an oracle" in prompt
    assert "not as clinical facts" in prompt
    assert "small experiment" in prompt


def test_astrologer_remains_fact_bound_while_getting_a_distinct_voice() -> None:
    prompt = load_horoscope_prompts("astrologer-v2").system

    assert "only permitted source for astrology facts" in prompt
    assert "experienced astrologer" in prompt
    assert "generic life coach" in prompt


def test_renderer_copy_is_persona_specific() -> None:
    assert TAROT_FLOW.copy.main_theme_title == "Что показывает расклад"
    assert LOVE_ORACLE_FLOW.copy.main_theme_title == "Что между вами сейчас"
    assert MYSTICAL_PSYCHOLOGIST_FLOW.copy.main_theme_title == "Какой сценарий здесь виден"

    assert TAROT_FLOW.copy.hook.unlock_lines != LOVE_ORACLE_FLOW.copy.hook.unlock_lines
    assert LOVE_ORACLE_FLOW.copy.hook.unlock_lines != MYSTICAL_PSYCHOLOGIST_FLOW.copy.hook.unlock_lines
    assert TAROT_FLOW.copy.hook_by_symbol_set
