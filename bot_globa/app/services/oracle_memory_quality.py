"""Topic-neutral exact deduplication and staleness policy for oracle memory."""

import re
import unicodedata
from datetime import UTC, datetime, timedelta

from app.domain.oracle_memory import MemoryKind
from app.services.sensitive_content import (
    ContentPurpose,
    FingerprintingSensitiveContentCipher,
)

_WHITESPACE = re.compile(r"\s+")
_STALE_AFTER_DAYS: dict[MemoryKind, int | None] = {
    MemoryKind.USER_STATEMENT: 365,
    MemoryKind.USER_PREFERENCE: 730,
    MemoryKind.PERSONAL_GOAL: 365,
    MemoryKind.RELATIONSHIP_NOTES: 180,
    MemoryKind.RECURRING_THEME: 180,
    MemoryKind.BIRTH_PROFILE: None,
    MemoryKind.ORACLE_PREFERENCE: 730,
}


def normalize_memory_value(value: str) -> str:
    """Normalize formatting only; never remove content because of its topic."""

    normalized = unicodedata.normalize("NFKC", value)
    return _WHITESPACE.sub(" ", normalized).strip().casefold()


def memory_content_fingerprint(
    cipher: FingerprintingSensitiveContentCipher,
    kind: MemoryKind,
    value: str,
) -> str:
    """Produce a purpose-separated keyed identity without exposing plaintext."""

    return cipher.fingerprint_json(
        ContentPurpose.ORACLE_MEMORY_VALUE,
        {
            "identity_version": "oracle-memory-exact-v1",
            "kind": kind.value,
            "value": normalize_memory_value(value),
        },
    )


def memory_stale_after(kind: MemoryKind) -> timedelta | None:
    days = _STALE_AFTER_DAYS[kind]
    return timedelta(days=days) if days is not None else None


def memory_is_stale(
    kind: MemoryKind,
    created_at: datetime,
    *,
    now: datetime | None = None,
) -> bool:
    """Mark time-sensitive context stale without deleting or suppressing it."""

    lifetime = memory_stale_after(kind)
    if lifetime is None:
        return False
    observed_at = now or datetime.now(UTC)
    return created_at + lifetime <= observed_at


def memory_staleness_penalty(
    kind: MemoryKind,
    created_at: datetime,
    *,
    now: datetime | None = None,
) -> int:
    """Stale relevant memories remain eligible but rank below fresh equivalents."""

    return 35 if memory_is_stale(kind, created_at, now=now) else 0
