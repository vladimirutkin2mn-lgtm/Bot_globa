"""Fixed ORA-603 staging gate across all four MVP oracle directions."""

import json
import os
from datetime import date, time
from pathlib import Path
from typing import TypedDict, cast

import pytest

from app.domain.birth_profile import BirthProfileInput
from app.domain.horoscope import AstrologyReadingResult
from app.domain.natal_chart import NatalBody
from app.domain.reading_result import ReadingResult
from app.prompts.horoscope import load_horoscope_prompts
from app.prompts.oracle import load_oracle_reading_prompts
from app.services.natal_chart import AstronomyEngineNatalChartCalculator
from app.services.oracle_staging_quality import (
    build_oracle_deployment_snapshot,
    deployment_mismatches,
)
from app.services.reading_output_safety import (
    ReadingOutputSafetyError,
    ReadingOutputSafetyValidator,
)


class RuntimeDefaults(TypedDict):
    llm_provider: str
    llm_model: str


class PersonaCoordinate(TypedDict):
    code: str
    engine_version: str
    prompt_version: str
    schema_version: str


class VersionCoordinate(TypedDict):
    schema_version: str
    engine_version: str
    house_system: str


class HoroscopeCoordinate(TypedDict):
    facts_version: str
    schema_version: str
    renderer_version: str


class DeploymentFixture(TypedDict):
    personas: list[PersonaCoordinate]
    natal_chart: VersionCoordinate
    horoscope: HoroscopeCoordinate


class PersonaCase(TypedDict):
    persona: str
    required_prompt_fragments: list[str]
    safe_text: str
    unsafe_text: str
    unsafe_issue: str


class AstrologyExpected(TypedDict):
    calculation_utc: str
    time_precision: str
    planet_count: int
    house_count: int
    house_system: str | None
    sun_sign: str


class AstrologyCase(TypedDict):
    id: str
    birth_date: str
    birth_time: str | None
    birth_place: str
    timezone: str
    latitude: float
    longitude: float
    utc_offset_minutes: int
    expected: AstrologyExpected


class Dataset(TypedDict):
    version: str
    runtime_defaults: RuntimeDefaults
    deployment: DeploymentFixture
    schemas: dict[str, list[str]]
    persona_cases: list[PersonaCase]
    astrology_cases: list[AstrologyCase]


def _load_dataset() -> Dataset:
    path = Path(__file__).parent / "fixtures" / "oracle_staging_quality_v1.json"
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AssertionError("oracle staging fixture root must be an object")
    return cast(Dataset, raw)


DATASET = _load_dataset()
PERSONA_CASES = DATASET["persona_cases"]
ASTROLOGY_CASES = DATASET["astrology_cases"]


def _prompt_text(persona: str, prompt_version: str) -> str:
    if persona == "astrologer":
        horoscope_prompt = load_horoscope_prompts(prompt_version)
        return f"{horoscope_prompt.system}\n{horoscope_prompt.request_instruction}"
    reading_prompt = load_oracle_reading_prompts(prompt_version)
    return f"{reading_prompt.system}\n{reading_prompt.request_instruction}"


def test_staging_dataset_covers_exactly_four_deployed_personas() -> None:
    assert DATASET["version"] == "oracle-staging-quality-v1"
    assert [case["persona"] for case in PERSONA_CASES] == [
        "tarot_reader",
        "love_oracle",
        "mystical_psychologist",
        "astrologer",
    ]
    assert [persona["code"] for persona in DATASET["deployment"]["personas"]] == [
        case["persona"] for case in PERSONA_CASES
    ]


def test_deployed_prompt_schema_engine_and_model_versions_match_manifest() -> None:
    defaults = DATASET["runtime_defaults"]
    actual = build_oracle_deployment_snapshot(
        llm_provider=os.getenv("LLM_PROVIDER", defaults["llm_provider"]),
        llm_model=os.getenv("LLM_MODEL", defaults["llm_model"]),
    )
    expected = build_oracle_deployment_snapshot(
        llm_provider=os.getenv("ORACLE_STAGING_EXPECTED_LLM_PROVIDER", defaults["llm_provider"]),
        llm_model=os.getenv("ORACLE_STAGING_EXPECTED_LLM_MODEL", defaults["llm_model"]),
    )

    assert deployment_mismatches(actual, expected) == ()
    payload = actual.payload()
    assert payload["gate_version"] == DATASET["version"]
    assert payload["personas"] == DATASET["deployment"]["personas"]
    assert payload["natal_chart"] == DATASET["deployment"]["natal_chart"]
    assert payload["horoscope"] == DATASET["deployment"]["horoscope"]


def test_deployment_snapshot_reports_model_drift_without_private_data() -> None:
    expected = build_oracle_deployment_snapshot(llm_provider="openai", llm_model="approved-model")
    actual = build_oracle_deployment_snapshot(llm_provider="openai", llm_model="unexpected-model")

    assert deployment_mismatches(actual, expected) == ("llm_model",)


def test_structured_result_contracts_match_fixed_manifest() -> None:
    assert list(ReadingResult.model_fields) == DATASET["schemas"]["reading-result-v1"]
    assert (
        list(AstrologyReadingResult.model_fields)
        == DATASET["schemas"]["astrology-reading-result-v1"]
    )


@pytest.mark.parametrize(
    "case",
    PERSONA_CASES,
    ids=[case["persona"] for case in PERSONA_CASES],
)
def test_persona_style_contract_is_present_in_deployed_prompt(case: PersonaCase) -> None:
    coordinate = next(
        persona
        for persona in DATASET["deployment"]["personas"]
        if persona["code"] == case["persona"]
    )
    prompt_text = _prompt_text(case["persona"], coordinate["prompt_version"])

    for required in case["required_prompt_fragments"]:
        assert required in prompt_text


@pytest.mark.parametrize(
    "case",
    PERSONA_CASES,
    ids=[case["persona"] for case in PERSONA_CASES],
)
def test_persona_safety_examples_pass_and_fail_with_production_validator(
    case: PersonaCase,
) -> None:
    validator = ReadingOutputSafetyValidator()
    validator.validate_texts((("staging.safe_text", case["safe_text"]),))

    with pytest.raises(ReadingOutputSafetyError) as captured:
        validator.validate_texts((("staging.unsafe_text", case["unsafe_text"]),))

    assert any(issue.endswith(f":{case['unsafe_issue']}") for issue in captured.value.issues)
    assert case["unsafe_text"] not in str(captured.value)


@pytest.mark.parametrize(
    "case",
    ASTROLOGY_CASES,
    ids=[case["id"] for case in ASTROLOGY_CASES],
)
def test_fixed_astrology_calculation_cases(case: AstrologyCase) -> None:
    birth_time = None if case["birth_time"] is None else time.fromisoformat(case["birth_time"])
    profile = BirthProfileInput(
        birth_date=date.fromisoformat(case["birth_date"]),
        birth_time=birth_time,
        birth_place=case["birth_place"],
        timezone=case["timezone"],
        latitude=case["latitude"],
        longitude=case["longitude"],
        utc_offset_minutes=case["utc_offset_minutes"],
    )
    result = AstronomyEngineNatalChartCalculator().calculate(profile)
    expected = case["expected"]
    sun = next(position for position in result.planets if position.body is NatalBody.SUN)

    assert result.calculation_utc.isoformat() == expected["calculation_utc"]
    assert result.time_precision.value == expected["time_precision"]
    assert len(result.planets) == expected["planet_count"]
    assert len(result.houses) == expected["house_count"]
    assert result.house_system == expected["house_system"]
    assert sun.sign.value == expected["sun_sign"]
    if case["birth_time"] is None:
        assert result.ascendant_longitude_millidegrees is None
    else:
        assert result.ascendant_longitude_millidegrees is not None
