"""Unit coverage for strict oracle memory contracts."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.oracle_memory import (
    MemoryClaimBasis,
    MemoryCreateRequest,
    MemoryKind,
    MemorySourceType,
)


def test_memory_request_accepts_typed_values_without_topic_censorship() -> None:
    request = MemoryCreateRequest(
        kind=MemoryKind.USER_STATEMENT,
        value="  Пользователь сообщил о хроническом заболевании  ",
        confidence_milli=1000,
        claim_basis=MemoryClaimBasis.USER_STATED,
        source_type=MemorySourceType.USER_EXPLICIT,
        extraction_version="manual-v1",
    )

    assert request.value == "Пользователь сообщил о хроническом заболевании"
    assert request.kind is MemoryKind.USER_STATEMENT
    assert request.claim_basis is MemoryClaimBasis.USER_STATED


def test_memory_request_rejects_unknown_kind_and_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        MemoryCreateRequest(
            kind="unknown_memory_kind",  # type: ignore[arg-type]
            value="private",
            confidence_milli=1001,
            source_type=MemorySourceType.USER_EXPLICIT,
            extraction_version="manual-v1",
        )


def test_reading_derived_memory_requires_reading_provenance_and_candidate_key() -> None:
    with pytest.raises(ValidationError):
        MemoryCreateRequest(
            kind=MemoryKind.RECURRING_THEME,
            value="Повторяющийся выбор между безопасностью и переменами",
            confidence_milli=700,
            claim_basis=MemoryClaimBasis.MODEL_INFERRED,
            source_type=MemorySourceType.READING_DERIVED,
            extraction_version="extractor-v1",
        )

    reading_id = uuid4()
    with pytest.raises(ValidationError):
        MemoryCreateRequest(
            kind=MemoryKind.RECURRING_THEME,
            value="Повторяющийся выбор между безопасностью и переменами",
            confidence_milli=700,
            claim_basis=MemoryClaimBasis.MODEL_INFERRED,
            source_type=MemorySourceType.READING_DERIVED,
            source_reading_id=reading_id,
            extraction_version="extractor-v1",
        )

    request = MemoryCreateRequest(
        kind=MemoryKind.RECURRING_THEME,
        value="Повторяющийся выбор между безопасностью и переменами",
        confidence_milli=700,
        claim_basis=MemoryClaimBasis.MODEL_INFERRED,
        source_type=MemorySourceType.READING_DERIVED,
        source_reading_id=reading_id,
        source_persona_code="tarot_reader",
        extraction_version="extractor-v1",
        candidate_key="candidate-1",
    )
    assert request.source_reading_id == reading_id
    assert request.claim_basis is MemoryClaimBasis.MODEL_INFERRED


def test_non_reading_memory_rejects_forged_reading_link_or_candidate_key() -> None:
    with pytest.raises(ValidationError):
        MemoryCreateRequest(
            kind=MemoryKind.USER_PREFERENCE,
            value="Короткие ответы",
            confidence_milli=1000,
            source_type=MemorySourceType.USER_EXPLICIT,
            source_reading_id=uuid4(),
            extraction_version="manual-v1",
        )

    with pytest.raises(ValidationError):
        MemoryCreateRequest(
            kind=MemoryKind.USER_PREFERENCE,
            value="Короткие ответы",
            confidence_milli=1000,
            source_type=MemorySourceType.USER_EXPLICIT,
            extraction_version="manual-v1",
            candidate_key="forged",
        )
