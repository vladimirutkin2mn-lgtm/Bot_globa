from datetime import date

from aiogram.types import InlineKeyboardMarkup

from app.bot.group_social_handlers import (
    GROUP_SOCIAL_HELP,
    MIRROR_THEMES,
    _social_party_menu_keyboard,
    forecast_for_chat,
    individual_card_for_day,
    karma_for_day,
    mirror_card_for_day,
    role_day_for_chat,
    versus_for_day,
    week_summary_for_day,
)
from app.domain.tarot import RWS_78_V1


def _callbacks(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def test_social_party_menu_contains_only_distinct_party_mechanics() -> None:
    callbacks = _callbacks(_social_party_menu_keyboard())

    assert callbacks == [
        "group:party:who:0",
        "social:party:roles",
        "social:party:evening",
        "social:party:midnight",
        "social:party:secret",
        "social:party:mirror",
        "social:party:prediction",
        "social:party:cards",
    ]
    assert len(callbacks) == len(set(callbacks))
    assert all("archetype" not in callback for callback in callbacks)


def test_role_day_is_stable_and_uses_three_distinct_roles_and_cards() -> None:
    day = date(2026, 8, 17)

    first = role_day_for_chat(-1001234567890, day)
    second = role_day_for_chat(-1001234567890, day)

    assert first == second
    assert len(set(first.roles)) == 3
    assert len({card.code for card in first.cards}) == 3
    assert all(card in RWS_78_V1.cards for card in first.cards)


def test_group_forecast_is_stable_and_uses_three_distinct_cards() -> None:
    day = date(2026, 8, 17)

    first = forecast_for_chat(-1001234567890, day)
    second = forecast_for_chat(-1001234567890, day)

    assert first == second
    assert len({card.code for card in first}) == 3


def test_versus_is_symmetric_and_only_selects_the_two_participants() -> None:
    day = date(2026, 8, 17)

    forward = versus_for_day(101, 202, day)
    reverse = versus_for_day(202, 101, day)

    assert forward == reverse
    assert set(forward.winners) <= {101, 202}


def test_individual_card_is_stable_per_user_and_chat() -> None:
    day = date(2026, 8, 17)

    first = individual_card_for_day(-1001234567890, 101, day)
    second = individual_card_for_day(-1001234567890, 101, day)

    assert first == second
    assert first in RWS_78_V1.cards


def test_mirror_rejects_unknown_theme() -> None:
    day = date(2026, 8, 17)

    for theme in MIRROR_THEMES:
        assert mirror_card_for_day(-1001234567890, theme, day) in RWS_78_V1.cards

    try:
        mirror_card_for_day(-1001234567890, "unknown", day)
    except ValueError as exc:
        assert str(exc) == "unsupported mirror theme"
    else:
        raise AssertionError("unknown mirror theme must fail")


def test_karma_and_week_summary_are_stable() -> None:
    day = date(2026, 8, 17)

    karma = karma_for_day(-1001234567890, day)
    summary = week_summary_for_day(-1001234567890, day)

    assert karma == karma_for_day(-1001234567890, day)
    assert 1 <= karma[0] <= 7
    assert karma[1] in RWS_78_V1.cards
    assert summary == week_summary_for_day(-1001234567890, day)
    assert summary.main_card in RWS_78_V1.cards
    assert 0 <= summary.chaos_weekday <= 6


def test_group_help_exposes_all_new_entry_points() -> None:
    for command in ("/forecast", "/duel", "/versus", "/karma", "/week", "/roles", "/cards"):
        assert command in GROUP_SOCIAL_HELP
