"""Contracts for quick focuses in the personal day astrology flow."""

from app.bot import chat_scope_handlers, horoscope_intent
from app.bot import horoscope_flow as flow
from app.bot.daily_personal_topic_handlers import is_personal_day_context
from app.bot.daily_personal_topic_handlers import router as daily_personal_topic_router


def _callbacks() -> set[str]:
    return {
        button.callback_data
        for row in horoscope_intent.personal_daily_keyboard().inline_keyboard
        for button in row
        if button.callback_data is not None
    }


def test_personal_day_keyboard_offers_four_focuses_and_custom_question() -> None:
    callbacks = _callbacks()
    assert callbacks == {
        flow.callback("day", "focus", "love"),
        flow.callback("day", "focus", "work"),
        flow.callback("day", "focus", "money"),
        flow.callback("day", "focus", "general"),
        flow.callback("day", "custom"),
        flow.callback("menu"),
    }
    assert all(len(callback.encode("utf-8")) <= 64 for callback in callbacks)


def test_personal_day_focuses_have_server_authored_questions() -> None:
    assert set(horoscope_intent.PERSONAL_DAILY_FOCUS_QUESTIONS) == {
        "love",
        "work",
        "money",
        "general",
    }
    assert all(horoscope_intent.PERSONAL_DAILY_FOCUS_QUESTIONS.values())


def test_quick_day_callbacks_only_apply_to_the_live_day_forecast_topic() -> None:
    assert is_personal_day_context({"topic": horoscope_intent.DAY_FORECAST_INTENT}) is True
    assert is_personal_day_context({"topic": "love"}) is False
    assert is_personal_day_context({}) is False


def test_personal_day_router_is_wired_before_generic_persona_routers() -> None:
    assert daily_personal_topic_router in chat_scope_handlers.router.sub_routers
