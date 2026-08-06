"""Fact integrity and safety tests for structured Horoscope output."""

import json

import pytest

from app.services.horoscope_result_validator import (
    HoroscopeResultValidator,
    InvalidHoroscopeResult,
)
from tests.horoscope_helpers import sample_fact_bundle, valid_horoscope_payload


def test_validator_accepts_fact_bound_output() -> None:
    bundle = sample_fact_bundle()
    payload = valid_horoscope_payload(bundle)

    validated = HoroscopeResultValidator().validate(json.dumps(payload), bundle)

    assert validated.result.facts_digest == bundle.digest()
    assert validated.result.interpretations[0].fact_ids[0] in bundle.fact_ids


def test_validator_rejects_changed_digest_and_unknown_fact_reference() -> None:
    bundle = sample_fact_bundle()
    payload = valid_horoscope_payload(bundle)
    payload["facts_digest"] = "0" * 64
    interpretations = payload["interpretations"]
    assert isinstance(interpretations, list)
    first = interpretations[0]
    assert isinstance(first, dict)
    first["fact_ids"] = ["natal:planet:invented"]

    with pytest.raises(InvalidHoroscopeResult) as error:
        HoroscopeResultValidator().validate(json.dumps(payload), bundle)

    assert error.value.code == "invalid_semantics"
    assert "facts_digest:mismatch" in error.value.issues
    assert "interpretations.0.fact_ids:unknown" in error.value.issues


def test_validator_requires_exact_application_limitations() -> None:
    bundle = sample_fact_bundle()
    payload = valid_horoscope_payload(bundle)
    limitations = payload["limitations"]
    assert isinstance(limitations, list)
    limitations.append("birth_time_unknown")

    with pytest.raises(InvalidHoroscopeResult) as error:
        HoroscopeResultValidator().validate(json.dumps(payload), bundle)

    assert error.value.code == "invalid_semantics"
    assert error.value.issues == ("limitations:mismatch",)


def test_validator_forbids_model_authored_chart_positions() -> None:
    bundle = sample_fact_bundle()
    payload = valid_horoscope_payload(bundle)
    payload["overview"] = "Sun in Aries at 12° guarantees a decisive result."

    with pytest.raises(InvalidHoroscopeResult) as error:
        HoroscopeResultValidator().validate(json.dumps(payload), bundle)

    assert error.value.code == "invalid_semantics"
    assert "overview:raw_astrology_claim" in error.value.issues
    assert "overview:raw_degree_claim" in error.value.issues


def test_validator_reuses_shared_oracle_output_safety() -> None:
    bundle = sample_fact_bundle()
    payload = valid_horoscope_payload(bundle)
    payload["overview"] = "This will definitely happen and cannot be avoided."

    with pytest.raises(InvalidHoroscopeResult) as error:
        HoroscopeResultValidator().validate(json.dumps(payload), bundle)

    assert error.value.code == "unsafe_output"
    assert any("guaranteed_future" in issue for issue in error.value.issues)


def test_stored_result_is_schema_and_safety_checked_without_requiring_raw_facts() -> None:
    bundle = sample_fact_bundle()
    payload = valid_horoscope_payload(bundle)

    validated = HoroscopeResultValidator().validate_stored(payload)

    assert validated.result.scope is bundle.scope
    assert validated.result.facts_digest == bundle.digest()
