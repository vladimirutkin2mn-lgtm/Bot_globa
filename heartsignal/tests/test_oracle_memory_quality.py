"""Deterministic quality-policy coverage without private-value logging."""

from datetime import UTC, datetime, timedelta

from app.domain.memory_quality import MemoryQualitySummary
from app.domain.oracle_memory import MemoryKind
from app.services.oracle_memory_quality import (
    memory_content_fingerprint,
    memory_is_stale,
    memory_staleness_penalty,
    normalize_memory_value,
)
from app.services.sensitive_content import AESGCMSensitiveContentCipher


def test_exact_identity_normalizes_unicode_case_and_whitespace() -> None:
    cipher = AESGCMSensitiveContentCipher("ora-306-quality-unit-key")
    left = "  \uff26\uff49\uff4e\uff41\uff4e\uff43\uff49\uff41\uff4c\tStress  after Bankruptcy  "
    right = "financial stress after bankruptcy"

    assert normalize_memory_value(left) == right
    assert memory_content_fingerprint(cipher, MemoryKind.USER_STATEMENT, left) == (
        memory_content_fingerprint(cipher, MemoryKind.USER_STATEMENT, right)
    )
    assert memory_content_fingerprint(cipher, MemoryKind.PERSONAL_GOAL, right) != (
        memory_content_fingerprint(cipher, MemoryKind.USER_STATEMENT, right)
    )


def test_staleness_penalizes_but_never_expires_stable_birth_profile() -> None:
    now = datetime(2026, 8, 6, tzinfo=UTC)
    old_relationship = now - timedelta(days=181)
    old_birth_profile = now - timedelta(days=3650)

    assert memory_is_stale(MemoryKind.RELATIONSHIP_NOTES, old_relationship, now=now)
    assert (
        memory_staleness_penalty(
            MemoryKind.RELATIONSHIP_NOTES,
            old_relationship,
            now=now,
        )
        > 0
    )
    assert not memory_is_stale(MemoryKind.BIRTH_PROFILE, old_birth_profile, now=now)
    assert (
        memory_staleness_penalty(
            MemoryKind.BIRTH_PROFILE,
            old_birth_profile,
            now=now,
        )
        == 0
    )


def test_quality_summary_rejects_inconsistent_epistemic_counts() -> None:
    observed_at = datetime(2026, 8, 6, tzinfo=UTC)
    try:
        MemoryQualitySummary(
            active_count=2,
            user_stated_count=2,
            model_inferred_count=1,
            stale_count=0,
            correction_count=0,
            duplicate_group_count=0,
            observed_at=observed_at,
        )
    except ValueError as error:
        assert "epistemic counts" in str(error)
    else:
        raise AssertionError("inconsistent memory quality summary was accepted")
