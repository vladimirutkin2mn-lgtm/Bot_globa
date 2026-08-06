"""Strict storage-envelope tests for replayable Horoscope results."""

import json

import pytest

from app.domain.horoscope import AstrologyReadingResult
from app.services.horoscope_storage import (
    InvalidStoredHoroscope,
    deserialize_horoscope,
    serialize_horoscope,
)
from tests.horoscope_helpers import sample_fact_bundle, valid_horoscope_payload


def test_horoscope_result_and_facts_round_trip_through_json_storage() -> None:
    facts = sample_fact_bundle()
    result = AstrologyReadingResult.model_validate_json(
        json.dumps(valid_horoscope_payload(facts))
    )

    restored_result, restored_facts = deserialize_horoscope(
        serialize_horoscope(result, facts)
    )

    assert restored_result == result
    assert restored_facts == facts
    assert restored_result.facts_digest == restored_facts.digest()


def test_horoscope_envelope_rejects_unknown_version_and_extra_fields() -> None:
    facts = sample_fact_bundle()
    result = AstrologyReadingResult.model_validate_json(
        json.dumps(valid_horoscope_payload(facts))
    )
    envelope = serialize_horoscope(result, facts)
    envelope["envelope_version"] = "horoscope-envelope-v2"
    envelope["unexpected"] = True

    with pytest.raises(InvalidStoredHoroscope, match="invalid stored Horoscope envelope"):
        deserialize_horoscope(envelope)
