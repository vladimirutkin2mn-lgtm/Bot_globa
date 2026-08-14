"""Layout overflow is trimmed; anything that would make a reading wrong still fails."""

import json

import pytest

from app.domain.reading import ReadingSymbolInput, SymbolOrientation
from app.domain.reading_result import ReadingResult
from app.services.presentation_limits import clamp_presentation
from app.services.reading_result_validator import (
    InvalidReadingResultError,
    ReadingResultValidator,
)
from tests.test_reading_result_validator import _expected_symbols, _valid_payload


def _validated(payload: dict[str, object]) -> ReadingResult:
    return ReadingResultValidator().validate(json.dumps(payload), _expected_symbols()).result


def test_a_sentence_that_runs_long_no_longer_costs_the_whole_reading() -> None:
    """This is the failure users met: a reading discarded over a hundred characters."""

    payload = _valid_payload()
    payload["title"] = "Т" * 900

    result = _validated(payload)

    assert len(result.title) == 500
    assert result.title.endswith("…")


def test_a_trimmed_sentence_still_ends_on_a_word() -> None:
    payload = _valid_payload()
    payload["title"] = ("слово " * 200).strip()

    title = _validated(payload).title

    assert len(title) <= 500
    assert title.endswith("…") and " " in title
    assert "слов…" not in title


def test_extra_items_are_dropped_instead_of_rejected() -> None:
    payload = _valid_payload()
    payload["patterns"] = [f"Паттерн {index}" for index in range(12)]
    payload["reflection_questions"] = [f"Вопрос {index}" for index in range(9)]

    result = _validated(payload)

    assert len(result.patterns) == 7
    assert len(result.reflection_questions) == 5
    # The model leads with what matters most, so the tail is what goes.
    assert result.patterns[0] == "Паттерн 0"


def test_limits_inside_a_nested_model_are_applied_too() -> None:
    """`conditions` lives in `ReadingScenario`, reached by `$ref` from the root schema."""

    payload = _valid_payload()
    scenarios = payload["possible_scenarios"]
    assert isinstance(scenarios, list)
    scenarios[0] = {"scenario": "Пауза проясняет обмен.", "conditions": ["у" * 800] + ["ц"] * 9}

    result = _validated(payload)

    assert len(result.possible_scenarios[0].conditions) == 5
    assert len(result.possible_scenarios[0].conditions[0]) == 500


def test_naming_a_symbol_the_engine_did_not_draw_is_still_refused() -> None:
    """Trimming may never rescue a reading that misreports the spread."""

    payload = _valid_payload()
    symbols = payload["symbols"]
    assert isinstance(symbols, list)
    symbols[0]["symbol_id"] = "major_00"

    with pytest.raises(InvalidReadingResultError) as captured:
        _validated(payload)

    assert captured.value.code == "invalid_semantics"


def test_a_missing_field_is_still_refused_because_nothing_can_invent_it() -> None:
    payload = _valid_payload()
    del payload["practical_step"]

    with pytest.raises(InvalidReadingResultError) as captured:
        _validated(payload)

    assert captured.value.code == "invalid_schema"


def test_too_few_items_is_still_refused_for_the_same_reason() -> None:
    payload = _valid_payload()
    payload["possible_scenarios"] = []

    with pytest.raises(InvalidReadingResultError) as captured:
        _validated(payload)

    assert captured.value.code == "invalid_schema"


def test_a_wrong_type_is_still_refused() -> None:
    payload = _valid_payload()
    payload["title"] = 123

    with pytest.raises(InvalidReadingResultError) as captured:
        _validated(payload)

    assert captured.value.code == "invalid_schema"


def test_a_payload_within_its_limits_is_returned_untouched() -> None:
    payload = _valid_payload()

    clamped = clamp_presentation(payload, ReadingResult.model_json_schema())

    assert clamped == payload


def test_the_symbol_identifier_is_never_trimmed_into_something_else() -> None:
    """`symbol_id` is an identity, not layout: shortening it would invent a card."""

    payload = _valid_payload()
    symbols = payload["symbols"]
    assert isinstance(symbols, list)
    original = symbols[0]["symbol_id"]

    clamped = clamp_presentation(payload, ReadingResult.model_json_schema())

    assert clamped["symbols"][0]["symbol_id"] == original


def test_the_expected_symbols_still_drive_acceptance() -> None:
    expected = _expected_symbols()

    assert all(isinstance(symbol, ReadingSymbolInput) for symbol in expected)
    assert expected[0].orientation is SymbolOrientation.REVERSED
