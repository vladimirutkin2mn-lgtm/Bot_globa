from datetime import date

from app.domain.natal_chart import ZodiacSign
from app.services.daily_horoscope_editorial import (
    _DUPLICATE_OPENERS,
    _GENERAL_STORIES,
    _STORIES,
    _editorialize,
    build_editorial_daily_horoscope,
)
from app.services.daily_sky import DailySignForecast

MAX_EDITORIAL_STORY_CHARS = 64


def test_daily_editorial_library_never_uses_semicolons() -> None:
    stories = [story for pool in _STORIES.values() for story in pool]

    assert stories
    assert all(";" not in story for story in stories)
    assert all(";" not in story for story in _GENERAL_STORIES)
    assert all(len(story) <= MAX_EDITORIAL_STORY_CHARS for story in stories)
    assert all(len(story) <= MAX_EDITORIAL_STORY_CHARS for story in _GENERAL_STORIES)


def test_rendered_daily_horoscope_never_uses_semicolons() -> None:
    snapshot = build_editorial_daily_horoscope(date(2026, 8, 17))

    assert len(snapshot.signs) == 12
    assert all(";" not in item.text for item in snapshot.signs)


def test_duplicate_fallback_stays_natural_without_semicolon() -> None:
    used = set(_GENERAL_STORIES)
    item = DailySignForecast(next(iter(ZodiacSign)), "неизвестная тема: тестовый сигнал")

    result = _editorialize(item, date(2026, 8, 17), used)

    assert ";" not in result.text
    assert result.text.startswith(f"{_DUPLICATE_OPENERS[0]}: ")
    assert result.text.removeprefix(f"{_DUPLICATE_OPENERS[0]}: ") in _GENERAL_STORIES
