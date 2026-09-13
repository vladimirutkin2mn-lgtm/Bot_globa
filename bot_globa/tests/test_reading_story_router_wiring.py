"""Regression coverage for the My Stories dispatcher wiring."""

import inspect

from app.bot import main as bot_main


def test_story_routers_are_registered_before_legacy_readings_route() -> None:
    source = inspect.getsource(bot_main.create_dispatcher)

    story_registration = "dispatcher.include_router(reading_story_router)"
    continuation_registration = "dispatcher.include_router(reading_story_continuation_router)"
    legacy_registration = "dispatcher.include_router(core_router)"

    assert story_registration in source
    assert continuation_registration in source
    assert source.index(story_registration) < source.index(legacy_registration)
    assert source.index(continuation_registration) < source.index(legacy_registration)
