import inspect

from app.bot import reading_feedback_handlers


def test_off_question_feedback_uses_existing_preview_dependency() -> None:
    parameters = inspect.signature(reading_feedback_handlers.submit_reading_feedback).parameters

    assert "previews" in parameters
    assert "одну полноценную бесплатную попытку" in reading_feedback_handlers.OFF_QUESTION_RESCUE_TEXT
    assert "miss_off_question" in inspect.getsource(
        reading_feedback_handlers.submit_reading_feedback
    )
