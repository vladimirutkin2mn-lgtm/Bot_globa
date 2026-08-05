"""Telegram presentation coverage for the isolated tarot MVP flow."""

from uuid import uuid4

from app.bot.tarot_keyboards import (
    tarot_context_keyboard,
    tarot_result_keyboard,
    tarot_retry_keyboard,
    tarot_topics_keyboard,
)
from app.bot.tarot_renderer import TELEGRAM_LIMIT, TarotPreviewRenderer
from app.domain.reading_result import (
    ReadingResult,
    ReadingSafetyAssessment,
    ReadingScenario,
    ReadingSymbolResult,
    ShareCardPayload,
)
from app.services.reading_generation import (
    ReadingGenerationResult,
    ReadingGenerationStatus,
)
from app.services.symbolic_engine import TarotSymbolicEngine
from app.services.tarot_reading import TarotPreviewOutcome

PRIVATE_MARKER = "private-question-must-not-leak"


def _outcome(*, long: bool = False) -> TarotPreviewOutcome:
    reading_id = uuid4()
    cards = TarotSymbolicEngine().draw(reading_id, "three_card_v1")
    expansion = "A" * 1800 if long else "A bounded reflective explanation."
    result = ReadingResult(
        title="A reflective spread",
        opening=expansion,
        symbols=[
            ReadingSymbolResult(
                symbol_id=card.card.code,
                position=card.position,
                orientation=card.orientation,
                interpretation="A bounded interpretation.",
            )
            for card in cards
        ],
        patterns=["Separate urgency from importance."],
        possible_scenarios=[
            ReadingScenario(
                scenario="A pause makes trade-offs clearer.",
                conditions=["Write down the reversible parts."],
            )
        ],
        reflection_questions=["Which value needs protection?"],
        practical_step=expansion,
        uncertainty_note="The spread cannot determine external events.",
        share_card=ShareCardPayload(
            headline="A reflective spread",
            short_text="Pause before choosing.",
        ),
        safety=ReadingSafetyAssessment(high_risk_detected=False, categories=[]),
    )
    return TarotPreviewOutcome(
        reading_id=reading_id,
        spread_code="three_card_v1",
        cards=cards,
        generation=ReadingGenerationResult(
            ReadingGenerationStatus.COMPLETED,
            result=result,
        ),
    )


def test_renderer_exposes_bounded_preview_without_private_input() -> None:
    rendered = TarotPreviewRenderer().render(_outcome())
    text = "\n".join(rendered.chunks)

    assert "Ваш расклад" in text
    assert "Практический шаг" in text
    assert "развлекательная практика" in text
    assert PRIVATE_MARKER not in text
    assert all(0 < len(chunk) <= TELEGRAM_LIMIT for chunk in rendered.chunks)


def test_renderer_chunks_large_valid_sections_below_telegram_limit() -> None:
    rendered = TarotPreviewRenderer().render(_outcome(long=True))

    assert len(rendered.chunks) >= 2
    assert all(len(chunk) <= TELEGRAM_LIMIT for chunk in rendered.chunks)


def test_tarot_callbacks_contain_only_codes_or_reading_id() -> None:
    reading_id = uuid4()
    keyboards = (
        tarot_topics_keyboard(),
        tarot_context_keyboard(),
        tarot_result_keyboard(),
        tarot_retry_keyboard(reading_id),
    )
    callbacks = [
        button.callback_data or ""
        for keyboard in keyboards
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert callbacks
    assert all(PRIVATE_MARKER not in callback for callback in callbacks)
    assert all(len(callback.encode()) <= 64 for callback in callbacks)
    assert f"tarot:retry:{reading_id}" in callbacks
