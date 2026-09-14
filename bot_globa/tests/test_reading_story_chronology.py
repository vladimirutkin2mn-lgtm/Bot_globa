"""Story folders use reading chronology rather than attachment order."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.domain.reading_history import ReadingHistoryChoice
from app.services.reading_history import ReadingHistoryService

_OLDER_ID = UUID("11111111-1111-1111-1111-111111111111")
_NEWER_ID = UUID("22222222-2222-2222-2222-222222222222")
_TIE_HIGH_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")


def _choice(reading_id: UUID, created_at: datetime) -> ReadingHistoryChoice:
    return ReadingHistoryChoice(
        reading_id=reading_id,
        persona_code="tarot_reader",
        topic="decision",
        status="preview_ready",
        created_at=created_at,
    )


def test_story_readings_are_newest_first_regardless_of_attachment_order() -> None:
    now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    older = _choice(_OLDER_ID, now - timedelta(days=10))
    newer = _choice(_NEWER_ID, now)

    assert ReadingHistoryService._newest_first((older, newer)) == (newer, older)
    assert ReadingHistoryService._newest_first((newer, older)) == (newer, older)


def test_story_chronology_uses_deterministic_uuid_tiebreaker() -> None:
    created_at = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    low = _choice(_OLDER_ID, created_at)
    high = _choice(_TIE_HIGH_ID, created_at)

    assert ReadingHistoryService._newest_first((low, high)) == (high, low)


def test_story_chronology_handles_empty_story() -> None:
    assert ReadingHistoryService._newest_first(()) == ()
