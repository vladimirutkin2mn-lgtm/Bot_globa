"""Versioned encrypted envelope for replayable Horoscope results and facts."""

import json
from datetime import date, datetime
from typing import Literal, cast

from pydantic import Field, JsonValue, ValidationError

from app.domain.horoscope import (
    AstrologyReadingResult,
    FactId,
    HoroscopeFact,
    HoroscopeFactBundle,
    HoroscopeFactKind,
    HoroscopeLimitation,
    HoroscopeScope,
)
from app.domain.reading_result import StrictReadingResultModel

HOROSCOPE_ENVELOPE_VERSION = "horoscope-envelope-v1"


class StoredHoroscopeFact(StrictReadingResultModel):
    fact_id: FactId
    kind: HoroscopeFactKind
    details: dict[str, JsonValue]


class StoredHoroscopeFactBundle(StrictReadingResultModel):
    facts_version: str
    scope: HoroscopeScope
    calculated_at_utc: str
    period_start: str | None
    period_end: str | None
    natal_schema_version: str
    natal_engine_version: str
    facts: list[StoredHoroscopeFact] = Field(min_length=1, max_length=500)
    limitations: list[HoroscopeLimitation] = Field(min_length=2, max_length=6)


class StoredHoroscopeEnvelope(StrictReadingResultModel):
    envelope_version: Literal["horoscope-envelope-v1"]
    result: AstrologyReadingResult
    facts: StoredHoroscopeFactBundle


class InvalidStoredHoroscope(ValueError):
    """Safe storage error containing no persisted private or generated text."""


def serialize_horoscope(
    result: AstrologyReadingResult,
    facts: HoroscopeFactBundle,
) -> dict[str, object]:
    """Create one authenticated-encryption payload for result and exact supporting facts."""

    return {
        "envelope_version": HOROSCOPE_ENVELOPE_VERSION,
        "result": result.model_dump(mode="json"),
        "facts": facts.payload(),
    }


def deserialize_horoscope(
    payload: dict[str, object],
) -> tuple[AstrologyReadingResult, HoroscopeFactBundle]:
    """Strictly restore the immutable result and fact bundle from ciphertext plaintext."""

    try:
        envelope = StoredHoroscopeEnvelope.model_validate_json(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        facts = HoroscopeFactBundle(
            facts_version=envelope.facts.facts_version,
            scope=envelope.facts.scope,
            calculated_at_utc=datetime.fromisoformat(envelope.facts.calculated_at_utc),
            period_start=(
                None
                if envelope.facts.period_start is None
                else date.fromisoformat(envelope.facts.period_start)
            ),
            period_end=(
                None
                if envelope.facts.period_end is None
                else date.fromisoformat(envelope.facts.period_end)
            ),
            natal_schema_version=envelope.facts.natal_schema_version,
            natal_engine_version=envelope.facts.natal_engine_version,
            facts=tuple(
                HoroscopeFact(
                    fact_id=fact.fact_id,
                    kind=fact.kind,
                    details=cast(dict[str, object], fact.details),
                )
                for fact in envelope.facts.facts
            ),
            limitations=tuple(envelope.facts.limitations),
        )
    except (ValidationError, TypeError, ValueError) as exc:
        raise InvalidStoredHoroscope("invalid stored Horoscope envelope") from exc
    return envelope.result, facts
