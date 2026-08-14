"""Telegram presentation coverage shared by every persona reading flow."""

from uuid import uuid4

import pytest

from app.bot.keyboards import main_menu_keyboard
from app.bot.persona_flow import PersonaFlow
from app.bot.persona_flows import (
    LOVE_ORACLE_FLOW,
    MVP_READING_FLOWS,
    MYSTICAL_PSYCHOLOGIST_FLOW,
    TAROT_FLOW,
)
from app.bot.reading_renderer import (
    TELEGRAM_LIMIT,
    render_full,
    render_micro_preview,
    render_preview,
)
from app.domain.reading_result import (
    ReadingResult,
    ReadingSafetyAssessment,
    ReadingScenario,
    ReadingSymbolResult,
    ShareCardPayload,
)
from app.services.persona_reading import PersonaPreviewOutcome
from app.services.reading_generation import (
    ReadingGenerationResult,
    ReadingGenerationStatus,
)
from app.services.symbolic_engine import TarotSymbolDrawer

PRIVATE_MARKER = "private-question-must-not-leak"


def _outcome(*, with_symbols: bool, long: bool = False) -> PersonaPreviewOutcome:
    reading_id = uuid4()
    drawer = TarotSymbolDrawer()
    contexts = drawer.draw(reading_id) if with_symbols else ()
    expansion = "A" * 1800 if long else "A bounded reflective explanation."
    result = ReadingResult(
        title="A reflective spread",
        opening=expansion,
        symbols=[
            ReadingSymbolResult(
                symbol_id=context.symbol.symbol_id,
                position=context.symbol.position,
                orientation=context.symbol.orientation,
                interpretation="A bounded interpretation.",
            )
            for context in contexts
        ],
        patterns=["Separate urgency from importance."],
        possible_scenarios=[
            ReadingScenario(
                scenario="A pause makes trade-offs clearer.",
                conditions=["Write down the reversible parts."],
            )
        ],
        reflection_questions=["Which value needs protection?"],
        practical_step=expansion,
        uncertainty_note="The spread cannot determine external events.",
        share_card=ShareCardPayload(
            headline="A reflective spread",
            short_text="Pause before choosing.",
        ),
        safety=ReadingSafetyAssessment(high_risk_detected=False, categories=[]),
    )
    return PersonaPreviewOutcome(
        reading_id=reading_id,
        generation=ReadingGenerationResult(ReadingGenerationStatus.COMPLETED, result=result),
        symbols=contexts,
        symbol_set_code=drawer.set_code if with_symbols else None,
    )


def test_preview_exposes_bounded_sections_without_private_input() -> None:
    chunks = render_preview(_outcome(with_symbols=True), TAROT_FLOW.copy)
    text = "\n".join(chunks)

    assert "Ваш расклад" in text
    assert TAROT_FLOW.copy.practical_step_title in text
    assert "развлекательная практика" in text
    assert PRIVATE_MARKER not in text
    assert all(0 < len(chunk) <= TELEGRAM_LIMIT for chunk in chunks)


def test_preview_omits_the_symbol_section_for_a_symbol_free_persona() -> None:
    chunks = render_preview(_outcome(with_symbols=False), LOVE_ORACLE_FLOW.copy)
    text = "\n".join(chunks)

    assert LOVE_ORACLE_FLOW.copy.drawn_symbols_title not in text
    assert LOVE_ORACLE_FLOW.copy.practical_step_title in text
    assert "развлекательная практика" in text


def test_full_render_names_drawn_symbols_and_stays_within_the_limit() -> None:
    outcome = _outcome(with_symbols=True)
    chunks = render_full(outcome, TAROT_FLOW.copy)
    text = "\n".join(chunks)

    assert "Полный расклад" in text
    assert TAROT_FLOW.copy.result_symbols_title in text
    for context in outcome.symbols:
        assert context.display_name in text
    assert all(len(chunk) <= TELEGRAM_LIMIT for chunk in chunks)


def test_micro_preview_gives_one_signal_without_the_paid_sections() -> None:
    outcome = _outcome(with_symbols=True)

    chunks = render_micro_preview(outcome, TAROT_FLOW.copy)
    text = "\n".join(chunks)

    assert "Разбор готов" in text
    assert "Separate urgency from importance." in text
    assert "развлекательная практика" in text
    # The paid depth is described, never delivered.
    assert TAROT_FLOW.copy.practical_step_title not in text
    assert "A pause makes trade-offs clearer." not in text
    assert "Which value needs protection?" not in text
    assert PRIVATE_MARKER not in text
    assert all(0 < len(chunk) <= TELEGRAM_LIMIT for chunk in chunks)


def test_micro_preview_still_names_the_symbols_that_were_already_fixed() -> None:
    outcome = _outcome(with_symbols=True)

    text = "\n".join(render_micro_preview(outcome, TAROT_FLOW.copy))

    for context in outcome.symbols:
        assert context.display_name in text


def test_micro_preview_is_shorter_than_the_first_free_preview() -> None:
    outcome = _outcome(with_symbols=True)

    micro = "\n".join(render_micro_preview(outcome, TAROT_FLOW.copy))
    preview = "\n".join(render_preview(outcome, TAROT_FLOW.copy))

    assert len(micro) < len(preview)


def test_renderer_chunks_large_valid_sections_below_telegram_limit() -> None:
    chunks = render_preview(_outcome(with_symbols=True, long=True), TAROT_FLOW.copy)

    assert len(chunks) >= 2
    assert all(len(chunk) <= TELEGRAM_LIMIT for chunk in chunks)


@pytest.mark.parametrize("flow", MVP_READING_FLOWS, ids=lambda flow: flow.persona_code)
def test_callbacks_carry_only_codes_or_reading_id_within_the_telegram_limit(
    flow: PersonaFlow,
) -> None:
    reading_id = uuid4()
    keyboards = (
        flow.topics_keyboard(),
        flow.context_keyboard(),
        flow.handoff_keyboard(),
        flow.result_keyboard(reading_id, 2),
        flow.retry_keyboard(reading_id),
        flow.history_keyboard(((reading_id, "Выбор · 05.08.2026"),), page=1, has_next=True),
    )
    callbacks = [
        button.callback_data or ""
        for keyboard in keyboards
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert callbacks
    assert all(PRIVATE_MARKER not in callback for callback in callbacks)
    assert all(len(callback.encode()) <= 64 for callback in callbacks)
    assert flow.callback("retry", str(reading_id)) in callbacks
    assert flow.callback("unlock", str(reading_id)) in callbacks
    assert flow.callback("history", "open", str(reading_id)) in callbacks
    assert flow.callback("history", "page", "0") in callbacks
    assert flow.callback("history", "page", "2") in callbacks


def test_every_flow_is_reachable_from_the_main_menu_under_a_unique_namespace() -> None:
    callbacks = {
        button.callback_data for row in main_menu_keyboard().inline_keyboard for button in row
    }
    namespaces = [flow.namespace for flow in MVP_READING_FLOWS]

    assert len(set(namespaces)) == len(namespaces)
    for flow in MVP_READING_FLOWS:
        assert f"menu:{flow.namespace}" in callbacks


def test_each_flow_uses_its_own_state_group() -> None:
    groups = {flow.states for flow in MVP_READING_FLOWS}

    assert len(groups) == len(MVP_READING_FLOWS)
    assert TAROT_FLOW.states is not MYSTICAL_PSYCHOLOGIST_FLOW.states
