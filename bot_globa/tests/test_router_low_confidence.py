from app.bot.personal_oracle_handlers import needs_route_clarification


def test_router_does_not_hide_unknown_intent_in_tarot_fallback() -> None:
    assert needs_route_clarification("Мне просто странно и я не понимаю происходящее") is True


def test_router_keeps_obvious_intents_fast() -> None:
    assert needs_route_clarification("Почему я опять откладываю важное решение?") is False
    assert needs_route_clarification("Что он ко мне чувствует?") is False
    assert needs_route_clarification("Сделай расклад на ближайшее будущее") is False
