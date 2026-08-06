"""Fixed safety regression gate shared by all planned oracle personas."""

import json
from pathlib import Path
from typing import TypedDict, cast

import pytest

from app.domain.oracle_safety import OracleInputSafetyClassifier
from app.domain.reading_result import ShareCardPayload
from app.services.oracle_safety_boundary import (
    OracleBoundaryError,
    OraclePromptBoundary,
    OracleShareSanitizer,
)
from app.services.reading_output_safety import (
    ReadingOutputSafetyError,
    ReadingOutputSafetyValidator,
)


class InputCase(TypedDict):
    id: str
    persona: str
    class_: str
    question: str
    context: str | None
    action: str
    categories: list[str]


class OutputCase(TypedDict):
    id: str
    persona: str
    path: str
    text: str
    issue: str


class BoundaryCase(TypedDict):
    id: str
    persona: str
    text: str


class ShareCase(TypedDict):
    id: str
    persona: str
    headline: str
    short_text: str
    private_fragments: list[str]
    issue: str


class Dataset(TypedDict):
    version: str
    personas: list[str]
    input_cases: list[dict[str, object]]
    output_cases: list[OutputCase]
    prompt_injection_cases: list[BoundaryCase]
    memory_injection_cases: list[BoundaryCase]
    share_cases: list[ShareCase]


def _load_dataset() -> Dataset:
    path = Path(__file__).parent / "fixtures" / "oracle_safety_regression_v1.json"
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AssertionError("oracle safety fixture root must be an object")
    return cast(Dataset, raw)


def _input_cases(dataset: Dataset) -> list[InputCase]:
    cases: list[InputCase] = []
    for raw in dataset["input_cases"]:
        case = dict(raw)
        case["class_"] = case.pop("class")
        cases.append(cast(InputCase, case))
    return cases


DATASET = _load_dataset()
INPUT_CASES = _input_cases(DATASET)
OUTPUT_CASES = DATASET["output_cases"]
PROMPT_CASES = DATASET["prompt_injection_cases"]
MEMORY_CASES = DATASET["memory_injection_cases"]
SHARE_CASES = DATASET["share_cases"]


@pytest.mark.parametrize("case", INPUT_CASES, ids=[case["id"] for case in INPUT_CASES])
def test_input_regression_case(case: InputCase) -> None:
    result = OracleInputSafetyClassifier().classify(case["question"], case["context"])

    assert result.action.value == case["action"]
    assert [category.value for category in result.categories] == case["categories"]


@pytest.mark.parametrize("case", OUTPUT_CASES, ids=[case["id"] for case in OUTPUT_CASES])
def test_output_regression_case(case: OutputCase) -> None:
    validator = ReadingOutputSafetyValidator()

    with pytest.raises(ReadingOutputSafetyError) as captured:
        validator.validate_texts(((case["path"], case["text"]),))

    assert case["issue"] in captured.value.issues
    assert case["text"] not in str(captured.value)


@pytest.mark.parametrize("case", PROMPT_CASES, ids=[case["id"] for case in PROMPT_CASES])
def test_prompt_injection_remains_json_data(case: BoundaryCase) -> None:
    wrapped = OraclePromptBoundary.wrap_input(
        {
            "persona_code": case["persona"],
            "user_question": case["text"],
        }
    )

    assert wrapped.startswith(OraclePromptBoundary.input_marker)
    payload_text = wrapped.removeprefix(OraclePromptBoundary.input_marker)
    decoded = cast(dict[str, object], json.loads(payload_text))
    assert decoded == {
        "persona_code": case["persona"],
        "user_question": case["text"],
    }
    assert case["text"] not in wrapped[: len(OraclePromptBoundary.input_marker)]


@pytest.mark.parametrize("case", MEMORY_CASES, ids=[case["id"] for case in MEMORY_CASES])
def test_malicious_memory_remains_tagged_json_data(case: BoundaryCase) -> None:
    wrapped = OraclePromptBoundary.wrap_memory(
        (
            {
                "source": "user_confirmed_memory",
                "persona_code": case["persona"],
                "value": case["text"],
            },
        )
    )

    assert wrapped.startswith(OraclePromptBoundary.memory_marker)
    payload_text = wrapped.removeprefix(OraclePromptBoundary.memory_marker)
    decoded = cast(dict[str, object], json.loads(payload_text))
    items = cast(list[dict[str, object]], decoded["items"])
    assert items[0]["source"] == "user_confirmed_memory"
    assert items[0]["value"] == case["text"]
    assert case["text"] not in wrapped[: len(OraclePromptBoundary.memory_marker)]


@pytest.mark.parametrize("case", SHARE_CASES, ids=[case["id"] for case in SHARE_CASES])
def test_share_regression_case(case: ShareCase) -> None:
    payload = ShareCardPayload(
        headline=case["headline"],
        short_text=case["short_text"],
    )

    with pytest.raises(OracleBoundaryError) as captured:
        OracleShareSanitizer().validate(
            payload,
            private_fragments=case["private_fragments"],
        )

    assert captured.value.code == "unsafe_share"
    assert case["issue"] in captured.value.issues
    assert case["short_text"] not in str(captured.value)


def test_safe_share_card_passes_without_private_fragments() -> None:
    OracleShareSanitizer().validate(
        ShareCardPayload(
            headline="A reflective pause",
            short_text="Compare possibilities without treating them as certainty.",
        )
    )


def test_dataset_covers_every_persona_and_risk_class() -> None:
    assert DATASET["version"] == "oracle-safety-regression-v1"
    personas = set(DATASET["personas"])
    assert personas == {
        "tarot_reader",
        "love_oracle",
        "mystical_psychologist",
        "horoscope",
    }
    for persona in personas:
        assert {case["class_"] for case in INPUT_CASES if case["persona"] == persona} == {
            "benign",
            "ambiguous",
            "adversarial",
        }
        assert any(case["persona"] == persona for case in OUTPUT_CASES)
        assert any(case["persona"] == persona for case in PROMPT_CASES)
        assert any(case["persona"] == persona for case in MEMORY_CASES)
        assert any(case["persona"] == persona for case in SHARE_CASES)
