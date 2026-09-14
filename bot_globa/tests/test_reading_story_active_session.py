"""Active story marker follows the same live-session rules as continuation."""

from app.bot.reading_story_handlers import _has_active_followup
from app.services.reading_followup import ReadingFollowUpStatus


def test_active_marker_survives_completed_answer_while_questions_remain() -> None:
    for status in (
        ReadingFollowUpStatus.READY,
        ReadingFollowUpStatus.COMPLETED,
        ReadingFollowUpStatus.CORRUPTED_HISTORY,
    ):
        assert _has_active_followup(status, 1) is True
        assert _has_active_followup(status, 0) is False


def test_active_marker_hides_non_askable_sessions() -> None:
    for status in (
        ReadingFollowUpStatus.EXPIRED,
        ReadingFollowUpStatus.NOT_ELIGIBLE,
        ReadingFollowUpStatus.PROCESSING,
        ReadingFollowUpStatus.INVALID_QUESTION,
        ReadingFollowUpStatus.FAILED_RELEASED,
    ):
        assert _has_active_followup(status, 2) is False
