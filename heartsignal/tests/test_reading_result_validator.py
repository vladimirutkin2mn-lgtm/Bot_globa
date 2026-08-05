"""Validation coverage for strict structured oracle results."""

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
        ),
        ReadingSymbolInput(
            symbol_id="major_07",
            position="hidden_factor",
            orientation=SymbolOrientation.REVERSED,
            catalog_version="tarot-major-v1",
        ),
        ReadingSymbolInput(
            symbol_id="major_06",
            position="next_step",
            orientation=SymbolOrientation.REVERSED,
            catalog_version="tarot-major-v1",
        ),
    ]


def _valid_payload() -> dict[str, object]:
    return {
        "title": "A choice that needs a slower review",
        "opening": "The spread points to a decision shaped by momentum and unfinished evaluation.",
        "symbols": [
            {
                "symbol_id": "major_20",
                "position": "current_influence",
                "orientation": "reversed",
                "interpretation": "Judgement reversed suggests postponing an honest review.",
            },
            {
                "symbol_id": "major_07",
                "position": "hidden_factor",
                "orientation": "reversed",
                "interpretation": "The Chariot reversed points to competing directions.",
            },
            {
                "symbol_id": "major_06",
                "position": "next_step",
                "orientation": "reversed",
                "interpretation": "The Lovers reversed asks for explicit value comparison.",
            },
        ],
        "patterns": ["Speed is replacing evaluation."],
        "possible_scenarios": [
            {
                "scenario": "A pause makes the trade-offs easier to compare.",
                "conditions": ["Write down the reversible and irreversible parts of each option."],
            }
        ],
        "reflection_questions": ["Which choice better matches the value you want to protect?"],
        "practical_step": "Compare both options in writing before committing.",
        "uncertainty_note": "The cards cannot determine which external offer will succeed.",
        "share_card": {
            "headline": "Your decision asks for a slower review",
            "short_text": "Compare values before momentum makes the choice for you.",
        },
        "safety": {"high_risk_detected": False, "categories": []},
    }


def test_valid_payload_preserves_exact_application_symbols() -> None:
    validation = ReadingResultValidator().validate(
        json.dumps(_valid_payload()),
        _expected_symbols(),
    )

    assert validation.schema_version == "reading-result-v1"
    assert [symbol.symbol_id for symbol in validation.result.symbols] == [
        "major_20",
        "major_07",
        "major_06",
    ]


def test_invalid_json_is_classified_without_payload_echo() -> None:
    secret = "private-question-marker"
    with pytest.raises(InvalidReadingResult) as captured:
        ReadingResultValidator().validate(f'{{"title":"{secret}"', _expected_symbols())

    assert captured.value.code == "invalid_json"
    assert secret not in str(captured.value)


def test_extra_field_and_wrong_scalar_type_are_rejected() -> None:
    payload = _valid_payload()
    payload["title"] = 123
    payload["unexpected"] = "field"

    with pytest.raises(InvalidReadingResult) as captured:
        ReadingResultValidator().validate(json.dumps(payload), _expected_symbols())

    assert captured.value.code == "invalid_schema"
    assert "title:invalid" in captured.value.issues
    assert "unexpected:invalid" in captured.value.issues


@pytest.mark.parametrize(
    ("field", "value", "expected_issue"),
    [
        ("symbol_id", "major_01", "symbols.0.symbol_id:mismatch"),
        ("position", "invented_position", "symbols.0.position:unexpected"),
        ("orientation", "upright", "symbols.0.orientation:mismatch"),
    ],
)
def test_model_cannot_replace_selected_symbol_contract(
    field: str,
    value: str,
    expected_issue: str,
) -> None:
    payload = _valid_payload()
    symbols = payload["symbols"]
    assert isinstance(symbols, list)
    first = symbols[0]
    assert isinstance(first, dict)
    first[field] = value

    with pytest.raises(InvalidReadingResult) as captured:
        ReadingResultValidator().validate(json.dumps(payload), _expected_symbols())

    assert captured.value.code == "invalid_semantics"
    assert expected_issue in captured.value.issues


def test_duplicate_or_missing_symbol_position_is_rejected() -> None:
    payload = _valid_payload()
    symbols = payload["symbols"]
    assert isinstance(symbols, list)
    symbols.pop()
    second = symbols[1]
    assert isinstance(second, dict)
    second["position"] = "current_influence"

    with pytest.raises(InvalidReadingResult) as captured:
        ReadingResultValidator().validate(json.dumps(payload), _expected_symbols())

    assert captured.value.code == "invalid_semantics"
    assert "symbols:duplicate_position" in captured.value.issues
    assert "symbols:count_mismatch" in captured.value.issues
    assert "symbols:missing_position" in captured.value.issues


def test_safety_flag_must_match_categories() -> None:
    payload = _valid_payload()
    safety = payload["safety"]
    assert isinstance(safety, dict)
    safety["categories"] = ["financial_or_gambling"]

    with pytest.raises(InvalidReadingResult) as captured:
        ReadingResultValidator().validate(json.dumps(payload), _expected_symbols())

    assert captured.value.code == "invalid_semantics"
    assert "safety:inconsistent_risk_flag" in captured.value.issues


def test_repair_instruction_contains_only_safe_issue_locations() -> None:
    error = InvalidReadingResult(
        "invalid_semantics",
        ("symbols.0.symbol_id:mismatch", "safety:inconsistent_risk_flag"),
    )

    instruction = ReadingResultValidator.repair_instruction(error)

    assert "symbols.0.symbol_id:mismatch" in instruction
    assert "safety:inconsistent_risk_flag" in instruction
    assert "private" not in instruction.lower()
