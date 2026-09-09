"""P1-05 free-answer and feedback tests without database or LLM I/O."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from aiogram.fsm.state import State, StatesGroup

from app.bot.persona_flow import (
    PersonaFlowTexts,
    ReadingFlow,
    feedback_reason_keyboard,
)
from app.bot.reading_feedback_handlers import _parse, submit_reading_feedback
from app.bot.reading_renderer import ReadingCopy, render_preview
from app.domain.reading import ReadingSymbolInput, SymbolOrientation
from app.domain.reading_generation import ReadingSymbolContext
from app.domain.reading_result import (
    ReadingResult,
    ReadingSafetyAssessment,
    ReadingScenario,
    ReadingSymbolResult,
    ShareCardPayload,
)
from app.services.persona_reading import PersonaPreviewOutcome
from app.services.reading_generation import ReadingGenerationResult, ReadingGenerationStatus


class TestStates(StatesGroup):
    waiting_for_question = State()
    waiting_for_context = State()
    generating = State()


def _outcome() -> PersonaPreviewOutcome:
    reading_id = uuid4()
    symbol_input = ReadingSymbolInput(
        symbol_id="star",
        position="focus",
        orientation=SymbolOrientation.UPRIGHT,
        catalog_version="v1",
    )
    result = ReadingResult(
        title="Сейчас важнее ясность",
        opening="Ты уже видишь направление, но пока проверяешь, можно ли ему доверять.",
        symbols=[
            ReadingSymbolResult(
                symbol_id="star",
                position="focus",
                orientation=SymbolOrientation.UPRIGHT,
                interpretation="Звезда здесь про спокойный ориентир, а не про резкий рывок.",
            ),
            ReadingSymbolResult(
                symbol_id="moon",
                position="hidden",
                orientation=SymbolOrientation.REVERSED,
                interpretation="Скрытая платная интерпретация второго символа.",
            ),
        ],
        patterns=["Платный паттерн, который не должен попасть в бесплатный ответ."],
        possible_scenarios=[
            ReadingScenario(
                scenario="Платный сценарий, который не должен попасть в бесплатный ответ.",
                conditions=["Платное условие"],
            )
        ],
        reflection_questions=["Платный вопрос для рефлексии?"],
        practical_step="Запиши один факт, который подтверждает выбранное направление.",
        uncertainty_note="Не воспринимай трактовку как гарантированный прогноз.",
        share_card=ShareCardPayload(headline="Ориентир", short_text="Смотри на факты."),
        safety=ReadingSafetyAssessment(high_risk_detected=False, categories=[]),
    )
    generation = ReadingGenerationResult(ReadingGenerationStatus.COMPLETED, result=result)
    return PersonaPreviewOutcome(
        reading_id=reading_id,
        generation=generation,
        symbols=(
            ReadingSymbolContext(
                symbol=symbol_input,
                display_name="Звезда",
                interpretation_theme="надежда и ориентир",
            ),
        ),
    )


def _flow() -> ReadingFlow:
    texts = PersonaFlowTexts(
        welcome="w",
        processing="p",
        opening="o",
        already_processing="a",
        unavailable="u",
        failed="f",
        history_title="h",
        history_empty="e",
        history_fallback="hf",
        locked="l",
        unlock_failed="uf",
        unlock_button="unlock",
        new_button="new",
    )
    return ReadingFlow(
        persona_code="tarot_reader",
        namespace="tarot",
        states=TestStates,
        topic_labels={},
        topic_examples={},
        texts=texts,
    )


def test_free_preview_is_useful_without_leaking_paid_sections() -> None:
    rendered = "\n".join(render_preview(_outcome(), ReadingCopy("✨", "Таро", "Карты", "Карты")))

    assert "Что видно:" in rendered
    assert "Ты уже видишь направление" in rendered
    assert "Образ:" in rendered
    assert "Звезда" in rendered
    assert "спокойный ориентир" in rendered
    assert "Небольшой шаг:" in rendered
    assert "Запиши один факт" in rendered
    assert "Платный сценарий" not in rendered
    assert "Платный паттерн" not in rendered
    assert "Платный вопрос" not in rendered
    assert "Скрытая платная интерпретация" not in rendered
    assert "В полном разборе" in rendered


def test_feedback_is_before_unlock_on_free_result() -> None:
    reading_id = uuid4()
    keyboard = _flow().result_keyboard(reading_id, "40 ⭐")

    assert [button.text for button in keyboard.inline_keyboard[0]] == ["Попало", "Мимо"]
    assert keyboard.inline_keyboard[1][0].text == "✨ Открыть глубокий разбор — 40 ⭐"
    assert keyboard.inline_keyboard[0][0].callback_data == f"rfb:hit:{reading_id}"
    assert keyboard.inline_keyboard[0][1].callback_data == f"rfb:miss:{reading_id}"


def test_miss_reason_keyboard_is_structured_and_optional() -> None:
    reading_id = uuid4()
    keyboard = feedback_reason_keyboard(reading_id)
    buttons = [row[0] for row in keyboard.inline_keyboard]

    assert [button.text for button in buttons] == [
        "Слишком общее",
        "Не про мой вопрос",
        "Непонятно",
        "Без причины",
    ]
    assert _parse(buttons[0].callback_data) == ("miss_too_general", reading_id)
    assert _parse(buttons[1].callback_data) == ("miss_off_question", reading_id)
    assert _parse(buttons[2].callback_data) == ("miss_unclear", reading_id)
    assert _parse(buttons[3].callback_data) == ("miss_plain", reading_id)


class FakeCallback:
    def __init__(self, data: str) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=12345)
        self.message = None
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text: str | None = None, *, show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))


class FakeOnboarding:
    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id

    async def current_user(self, telegram_user_id: int):
        return SimpleNamespace(id=self.user_id)


class FakeReadingHistory:
    def __init__(self, owns: bool = True) -> None:
        self.owns = owns
        self.ready_checks: list[tuple[UUID, UUID]] = []

    async def owns_ready(self, user_id: UUID, reading_id: UUID) -> bool:
        self.ready_checks.append((user_id, reading_id))
        return self.owns


class FakeOracleAnalytics:
    def __init__(self) -> None:
        self.events: list[tuple[UUID, object, dict[str, object]]] = []

    async def track(self, user_id: UUID, event: object, properties: dict[str, object]) -> None:
        self.events.append((user_id, event, properties))


@pytest.mark.asyncio
async def test_preview_feedback_uses_ready_authorization_and_tracks_hit() -> None:
    user_id, reading_id = uuid4(), uuid4()
    callback = FakeCallback(f"rfb:hit:{reading_id}")
    history = FakeReadingHistory()
    analytics = FakeOracleAnalytics()

    await submit_reading_feedback(
        callback,
        FakeOnboarding(user_id),
        history,
        analytics,
    )

    assert history.ready_checks == [(user_id, reading_id)]
    assert len(analytics.events) == 1
    assert analytics.events[0][2] == {"reading_id": reading_id, "reaction_code": "hit"}


@pytest.mark.asyncio
async def test_base_miss_does_not_emit_feedback_before_reason_choice() -> None:
    user_id, reading_id = uuid4(), uuid4()
    callback = FakeCallback(f"rfb:miss:{reading_id}")
    analytics = FakeOracleAnalytics()

    await submit_reading_feedback(
        callback,
        FakeOnboarding(user_id),
        FakeReadingHistory(),
        analytics,
    )

    assert analytics.events == []
    assert callback.answers == [(None, False)]
