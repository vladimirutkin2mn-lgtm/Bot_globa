"""P0 first-use routing regressions from the 2026-09-12 CJM review."""

from typing import Any

from app.bot import personal_oracle_handlers as handlers
from app.bot.persona_flows import LOVE_ORACLE_FLOW, MYSTICAL_PSYCHOLOGIST_FLOW, TAROT_FLOW
from app.bot.states import OnboardingStates


class FakeState:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = dict(data or {})
        self.state: object | None = None

    async def get_data(self) -> dict[str, Any]:
        return dict(self.data)

    async def update_data(self, data: dict[str, Any] | None = None, **kwargs: Any) -> None:
        if data:
            self.data.update(data)
        self.data.update(kwargs)

    async def set_state(self, state: object | None) -> None:
        self.state = state

    async def clear(self) -> None:
        self.data.clear()
        self.state = None


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.answers: list[str] = []

    async def answer(self, text: str, **_: Any) -> None:
        self.answers.append(text)


def test_work_change_language_does_not_fall_into_love_oracle() -> None:
    for question in (
        "Я чувствую, что выгораю на работе",
        "Хочу изменить работу, но боюсь",
        "Как изменить карьеру?",
        "Отношения с начальником изменились",
    ):
        choice = handlers.choose_route(question)
        assert choice.flow is TAROT_FLOW
        assert choice.topic == "work"


def test_reflective_relationship_pattern_is_recognized_as_reflection() -> None:
    choice = handlers.choose_route("Почему меня снова тянет к недоступным мужчинам?")
    assert choice.flow is MYSTICAL_PSYCHOLOGIST_FLOW
    assert choice.topic == "repeating_pattern"


def test_mixed_work_and_relationship_request_gets_one_clarification() -> None:
    assert handlers.needs_route_clarification("Отношения с начальником изменились")
    assert handlers.needs_route_clarification("Люблю коллегу, но хочу уйти с работы")
    assert not handlers.needs_route_clarification("Хочу изменить работу, но боюсь")


def test_explicit_practice_is_preserved_while_topic_changes() -> None:
    tarot = handlers.route_within_practice("Я снова хожу по одному и тому же кругу", "tarot")
    assert tarot is not None
    assert tarot.flow is TAROT_FLOW
    assert tarot.topic == "repeating_pattern"

    love = handlers.route_within_practice("Он снова сближается, а потом исчезает", "love")
    assert love is not None
    assert love.flow is LOVE_ORACLE_FLOW
    assert love.topic == "repeating_pattern"

    unrelated_love = handlers.route_within_practice("Как изменить карьеру?", "love")
    assert unrelated_love is not None
    assert unrelated_love.flow is LOVE_ORACLE_FLOW


async def test_first_text_before_consent_is_saved_without_generation(monkeypatch: Any) -> None:
    screens: list[tuple[object, str]] = []

    async def fake_show_screen(
        message: object,
        scene: object,
        text: str,
        **_: Any,
    ) -> None:
        screens.append((scene, text))

    monkeypatch.setattr(handlers, "show_screen", fake_show_screen)
    state = FakeState()
    message = FakeMessage("Хочу понять, стоит ли менять работу")

    await handlers.capture_question_before_consent(
        message,
        state,
        30,
    )

    assert state.data["personal_oracle_pending_question"] == message.text
    assert state.data["personal_oracle_mode"] == "auto"
    assert state.state is OnboardingStates.waiting_for_consent
    assert len(screens) == 1
    assert "соглас" in screens[0][1].casefold() or "данн" in screens[0][1].casefold()
    assert message.answers == []


def test_preconsent_plain_text_filter_does_not_capture_commands() -> None:
    filter_ = handlers.PlainTextBeforeConsentFilter()

    import asyncio

    assert asyncio.run(filter_(FakeMessage("Расскажу ситуацию")))  # type: ignore[arg-type]
    assert not asyncio.run(filter_(FakeMessage("/help")))  # type: ignore[arg-type]
