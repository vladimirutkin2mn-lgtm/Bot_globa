"""Unit coverage for strict oracle memory contracts."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.oracle_memory import (
    MemoryCreateRequest,
    MemoryKind,
    MemorySourceType,
)


def test_memory_request_accepts_only_allow_listed_typed_values() -> None:
    request = MemoryCreateRequest(
        kind=MemoryKind.PERSONAL_GOAL,
        value="  Спокойнее обозначать свои границы  ",
        confidence_milli=850,
        source_type=MemorySourceType.USER_EXPLICIT,
        extraction_version="manual-v1",
    )

    assert request.value == "Спокойнее обозначать свои границы"
    assert request.kind is MemoryKind.PERSONAL_GOAL


def test_memory_request_rejects_unknown_kind_and_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        MemoryCreateRequest(
            kind="medical_diagnosis",  # type: ignore[arg-type]
            value="private",
            confidence_milli=1001,
            source_type=MemorySourceType.USER_EXPLICIT,
            extraction_version="manual-v1",
        )


def test_reading_derived_memory_requires_reading_provenance() -> None:
    with pytest.raises(ValidationError):
        MemoryCreateRequest(
            kind=MemoryKind.RECURRING_THEME,
            value="Повторяющийся выбор между безопасностью и переменами",
            confidence_milli=700,
            source_type=MemorySourceType.READING_DERIVED,
            extraction_version="extractor-v1",
        )

    request = MemoryCreateRequest(
        kind=MemoryKind.RECURRING_THEME,
        value="Повторяющийся выбор между безопасностью и переменами",
        confidence_milli=700,
        source_type=MemorySourceType.READING_DERIVED,
        source_reading_id=uuid4(),
        source_persona_code="tarot_reader",
        extraction_version="extractor-v1",
    )
    assert request.source_reading_id is not None


def test_non_reading_memory_rejects_forged_reading_link() -> None:
    with pytest.raises(ValidationError):
        MemoryCreateRequest(
            kind=MemoryKind.USER_PREFERENCE,
            value="Короткие ответы",
            confidence_milli=1000,
            source_type=MemorySourceType.USER_EXPLICIT,
            source_reading_id=uuid4(),
            extraction_version="manual-v1",
        )
