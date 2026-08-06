"""Output safety coverage for structured oracle readings."""

import json

import pytest

from app.domain.reading import ReadingSymbolInput, SymbolOrientation
from app.services.reading_result_validator import InvalidReadingResult, ReadingResultValidator


def _expected_symbols() -> list[ReadingSymbolInput]:
    return [
        ReadingSymbolInput(
            symbol_id="major_20",
            position="current_influence",
            orientation=SymbolOrientation.REVERSED,
            catalog_version="tarot-major-v1",
        )
    ]


def _payload() -> dict[str, object]:
    return {
        "title": "A reflective pause",
        "opening": "The spread invites comparison without promising an outcome.",
        "symbols": [
            {
                "symbol_id": "major_20",
                "position": "current_influence",
                "orientation": "reversed",
                "interpretation": "Judgement reversed may point to an unfinished review.",
            }
        ],
        "patterns": ["Momentum may be replacing evaluation."],
        "possible_scenarios": [
            {
                "scenario": "A pause could make the trade-offs easier to compare.",
                "conditions": ["Write down what is reversible before deciding."],
            }
        ],
        "reflection_questions": ["Which value do you want to protect?"],
        "practical_step": "Compare both options in writing.",
        "uncertainty_note": (
            "The cards cannot guarantee what will happen or know another person's thoughts."
        ),
        "share_card": {
            "headline": "Pause before momentum decides",
            "short_text": "Use the reading as reflection, not certainty.",
        },
        "safety": {"high_risk_detected": False, "categories": []},
    }


def _validate(payload: dict[str, object]) -> None:
    ReadingResultValidator().validate(json.dumps(payload), _expected_symbols())


def test_reflective_uncertainty_language_is_allowed() -> None:
    _validate(_payload())


@pytest.mark.parametrize(
    ("field", "value", "expected_issue"),
    [
        ("title", "They will definitely return next week.", "output.title:guaranteed_future"),
        (
            "opening",
            "I know exactly what he thinks about you.",
            "output.opening:third_party_mind_reading",
        ),
        (
            "practical_step",
            "Invest all your money in this opportunity.",
            "output.practical_step:financial_or_gambling",
        ),
        (
            "uncertainty_note",
            "You are diagnosed with depression.",
            "output.uncertainty_note:medical",
        ),
        (
            "opening",
            "You will win the court case.",
            "output.opening:legal",
        ),
        (
            "practical_step",
            "You should die.",
            "output.practical_step:self_harm",
        ),
    ],
)
def test_unsafe_top_level_claims_are_rejected(
    field: str,
    value: str,
    expected_issue: str,
) -> None:
    payload = _payload()
    payload[field] = value

    with pytest.raises(InvalidReadingResult) as captured:
        _validate(payload)

    assert captured.value.code == "unsafe_output"
    assert expected_issue in captured.value.issues
    assert value not in str(captured.value)


def test_nested_symbol_interpretation_is_checked() -> None:
    payload = _payload()
    symbols = payload["symbols"]
    assert isinstance(symbols, list)
    symbol = symbols[0]
    assert isinstance(symbol, dict)
    symbol["interpretation"] = "Track her without her knowledge."

    with pytest.raises(InvalidReadingResult) as captured:
        _validate(payload)

    assert captured.value.code == "unsafe_output"
    assert "output.symbols.0.interpretation:violence_or_stalking" in captured.value.issues


def test_nested_scenario_condition_is_checked() -> None:
    payload = _payload()
    scenarios = payload["possible_scenarios"]
    assert isinstance(scenarios, list)
    scenario = scenarios[0]
    assert isinstance(scenario, dict)
    conditions = scenario["conditions"]
    assert isinstance(conditions, list)
    conditions[0] = "Do not make decisions without another reading."

    with pytest.raises(InvalidReadingResult) as captured:
        _validate(payload)

    assert captured.value.code == "unsafe_output"
    assert (
        "output.possible_scenarios.0.conditions.0:dependency" in captured.value.issues
    )


def test_share_card_fear_based_upsell_is_checked() -> None:
    payload = _payload()
    share_card = payload["share_card"]
    assert isinstance(share_card, dict)
    share_card["short_text"] = "You are cursed; pay now to remove the curse."

    with pytest.raises(InvalidReadingResult) as captured:
        _validate(payload)

    assert captured.value.code == "unsafe_output"
    assert "output.share_card.short_text:fear_based_upsell" in captured.value.issues


def test_repair_instruction_contains_only_safe_issue_codes() -> None:
    secret = "private-generated-marker"
    payload = _payload()
    payload["title"] = f"They will definitely return. {secret}"

    with pytest.raises(InvalidReadingResult) as captured:
        _validate(payload)

    instruction = ReadingResultValidator.repair_instruction(captured.value)

    assert "output.title:guaranteed_future" in instruction
    assert "conditional and reflective wording" in instruction
    assert secret not in instruction
    assert secret not in str(captured.value)
