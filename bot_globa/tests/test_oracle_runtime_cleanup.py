"""Regression coverage for removing the imported HeartSignal product from runtime."""

import inspect

from app.bot import main, oracle_dependencies, texts
from app.bot.keyboards import daily_horoscope_keyboard, main_menu_keyboard, more_menu_keyboard
from app.bot.persona_flows import LOVE_ORACLE_FLOW


def _callback_data() -> set[str]:
    return {
        button.callback_data
        for keyboard in (main_menu_keyboard(), more_menu_keyboard())
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    }


def test_main_menu_contains_only_active_oracle_navigation() -> None:
    callbacks = _callback_data()

    # All four MVP personas are reachable; each flow owns its own history screen, so the
    # menu carries no persona-specific history entry.
    assert {"menu:tarot", "menu:love", "menu:psy", "menu:astro"} <= callbacks
    assert not any(callback.startswith("tarot:") for callback in callbacks)
    assert "menu:memory" in callbacks
    assert "menu:balance" in callbacks
    assert "menu:privacy" in callbacks
    assert "menu:analyze" not in callbacks
    assert "menu:history" not in callbacks


def test_runtime_composition_does_not_register_heartsignal_routes() -> None:
    source = inspect.getsource(main)

    assert "app.bot.handlers" not in source
    # The reading follow-up router is the oracle one; the legacy analysis router is not
    # imported at all, so match the module path rather than a bare substring.
    assert "app.bot.followup_handlers" not in source
    assert "app.bot.reading_followup_handlers" in source
    assert "OnboardingDependencyMiddleware" not in source
    assert "OracleDependencyMiddleware" in source


def test_active_dependency_middleware_does_not_build_analysis_stack() -> None:
    source = inspect.getsource(oracle_dependencies)

    for legacy_name in (
        "ConversationParser",
        "ConversationIntakeService",
        "create_analysis_service",
        "MonetizedAnalysisService",
        "FollowUpService",
        "ReportRenderer",
        "ReportService",
        "SqlAlchemyAnalysisRepository",
    ):
        assert legacy_name not in source


def test_active_client_copy_uses_consumer_brand() -> None:
    daily_button = daily_horoscope_keyboard().inline_keyboard[1][0].text
    branded_copy = (
        texts.WELCOME,
        texts.MEMORY_CONSENT_OFFER,
        LOVE_ORACLE_FLOW.texts.welcome,
        daily_button,
    )

    assert texts.BRAND_NAME == "Numa"
    assert all("HeartSignal" not in value for value in branded_copy)
    assert all("Globa" not in value for value in branded_copy)
    assert all(texts.BRAND_NAME in value for value in branded_copy)
