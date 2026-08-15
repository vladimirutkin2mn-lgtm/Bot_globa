"""Conversion hooks create curiosity without inventing private facts or future certainty."""

import json
from uuid import uuid4

from app.bot.conversion_hooks import ConversionHookCopy, render_grounded_hook
from app.bot.horoscope_renderer import HoroscopeRenderer
from app.bot.persona_flows import TAROT_FLOW
from app.bot.reading_renderer import render_micro_preview, render_preview
from app.domain.horoscope import AstrologyReadingResult
from app.domain.reading import SymbolOrientation
from app.domain.reading_result import ReadingResult, ReadingScenario
from app.services.persona_reading import PersonaPreviewOutcome
from app.services.preview_entitlement import ReadingPreviewVisibility
from app.services.reading_generation import ReadingGenerationResult, ReadingGenerationStatus
from tests.horoscope_helpers import sample_fact_bundle, valid_horoscope_payload
from tests.test_reading_result_validator import _valid_payload


def _two_scenario_reading() -> ReadingResult:
    payload = _valid_payload()
    symbols = payload["symbols"]
    assert isinstance(symbols, list)
    for symbol in symbols:
        assert isinstance(symbol, dict)
        orientation = symbol["orientation"]
        assert isinstance(orientation, str)
        symbol["orientation"] = SymbolOrientation(orientation)

    scenarios = payload["possible_scenarios"]
    assert isinstance(scenarios, list)
    scenarios.append(
        {
            "scenario": "A faster commitment keeps momentum but leaves the trade-offs unresolved.",
            "conditions": ["Commit before the unanswered questions are compared."],
        }
    )
    return ReadingResult.model_validate(payload)


def _preview_outcome(result: ReadingResult, *, symbol_set_code: str) -> PersonaPreviewOutcome:
    return PersonaPreviewOutcome(
        reading_id=uuid4(),
        generation=ReadingGenerationResult(
            status=ReadingGenerationStatus.COMPLETED,
            result=result,
        ),
        symbol_set_code=symbol_set_code,
        visibility=ReadingPreviewVisibility.PREVIEW,
    )


def test_hook_reveals_a_real_scenario_but_keeps_its_conditions_paid() -> None:
    scenarios = [
        ReadingScenario(
            scenario="Связь становится теплее после более ясного разговора.",
            conditions=["Оба человека прямо называют ожидания."],
        ),
        ReadingScenario(
            scenario="Дистанция сохраняется.",
            conditions=["Неопределённость остаётся без обсуждения."],
        ),
    ]
    copy = ConversionHookCopy(
        branch_title="Есть развилка.",
        single_title="Есть одна линия.",
        scenario_prefix="Один сценарий:",
        hidden_conditions_line="Условия остаются в полном разборе.",
        alternative_line="Есть и другая траектория.",
        unlock_title="После открытия:",
        unlock_lines=("условия первого сценария", "условия второго сценария"),
    )

    hook = render_grounded_hook(scenarios, copy)

    assert scenarios[0].scenario in hook
    assert scenarios[0].conditions[0] not in hook
    assert scenarios[1].scenario not in hook
    assert "Есть и другая траектория" in hook
    assert "условия первого сценария" in hook


def test_tarot_decision_preview_uses_spread_specific_value_and_withholds_action() -> None:
    result = _two_scenario_reading()
    outcome = _preview_outcome(result, symbol_set_code="decision_five_v1")

    rendered = "\n".join(render_preview(outcome, TAROT_FLOW.copy))

    assert result.possible_scenarios[0].scenario in rendered
    assert result.possible_scenarios[0].conditions[0] not in rendered
    assert result.practical_step not in rendered
    assert "что даёт вариант A" in rendered
    assert "что даёт вариант B" in rendered
    assert "другая линия" in rendered


def test_micro_preview_keeps_the_same_grounded_open_loop() -> None:
    result = _two_scenario_reading()
    outcome = _preview_outcome(result, symbol_set_code="pattern_five_v1")

    rendered = "\n".join(render_micro_preview(outcome, TAROT_FLOW.copy))

    assert result.patterns[0] in rendered
    assert result.possible_scenarios[0].scenario in rendered
    assert result.possible_scenarios[0].conditions[0] not in rendered
    assert result.practical_step not in rendered
    assert "что запускает повторяющийся цикл" in rendered
    assert "точка" in rendered


def test_astrology_preview_uses_validated_scenario_without_revealing_conditions_or_action() -> None:
    bundle = sample_fact_bundle()
    payload = valid_horoscope_payload(bundle)
    scenarios = payload["possible_scenarios"]
    assert isinstance(scenarios, list)
    scenarios.append(
        {
            "scenario": "A second route becomes more relevant when the pace changes.",
            "conditions": ["The surrounding commitments become less rigid."],
        }
    )
    result = AstrologyReadingResult.model_validate_json(json.dumps(payload))

    rendered = HoroscopeRenderer().render_preview(result, bundle).text

    assert result.possible_scenarios[0].scenario in rendered
    assert result.possible_scenarios[0].conditions[0] not in rendered
    assert result.practical_step not in rendered
    assert "другая траектория" in rendered
    assert "дополнительные расчётные опоры" in rendered


def test_persona_hooks_do_not_use_fear_or_fake_mind_reading_as_the_upsell() -> None:
    copies = [
        TAROT_FLOW.copy.hook,
        *(hook for _code, hook in TAROT_FLOW.copy.hook_by_symbol_set),
    ]
    text = " ".join(
        " ".join(
            (
                hook.branch_title,
                hook.single_title,
                hook.hidden_conditions_line,
                hook.alternative_line,
                *hook.unlock_lines,
            )
        )
        for hook in copies
    ).lower()

    assert "опасност" not in text
    assert "угроз" not in text
    assert "точно произойд" not in text
    assert "он думает" not in text
    assert "она думает" not in text
