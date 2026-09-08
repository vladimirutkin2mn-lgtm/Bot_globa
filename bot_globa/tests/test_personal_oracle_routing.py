"""Regression coverage for the unified personal-oracle router."""

import pytest

from app.bot.personal_oracle_handlers import (
    choose_route,
    needs_route_clarification,
    route_from_clarification,
)


@pytest.mark.parametrize(
    ("question", "persona_code", "topic"),
    [
        ("Я чувствую, что выгораю на работе", "tarot_reader", "work"),
        ("У меня сложные отношения с начальником", "tarot_reader", "work"),
        ("Что он ко мне чувствует?", "love_oracle", "love"),
        ("Стоит ли написать ему первой?", "love_oracle", "communication"),
    ],
)
def test_contextual_route_matches_acceptance_examples(
    question: str,
    persona_code: str,
    topic: str,
) -> None:
    choice = choose_route(question)

    assert choice.flow.persona_code == persona_code
    assert choice.topic == topic
    assert not needs_route_clarification(question)


def test_broad_relationship_wording_requests_short_clarification() -> None:
    question = "У меня сложные отношения, и я не понимаю, что чувствую"

    assert needs_route_clarification(question)


def test_explicit_clarification_choice_has_priority() -> None:
    question = "У меня сложные отношения"

    love = route_from_clarification(question, "love")
    reflection = route_from_clarification(question, "reflection")
    work = route_from_clarification(question, "work")

    assert love is not None and love.flow.persona_code == "love_oracle"
    assert reflection is not None and reflection.flow.persona_code == "mystical_psychologist"
    assert work is not None and work.flow.persona_code == "tarot_reader"


def test_unknown_clarification_choice_is_rejected() -> None:
    assert route_from_clarification("У меня сложные отношения", "unknown") is None
