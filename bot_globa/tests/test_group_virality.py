from datetime import date
import re

import pytest

from app.bot.commands import GROUP_COMMANDS
from app.bot.group_handlers import (
    GROUP_EVENT_KINDS,
    GROUP_HELP,
    compatibility_for_day,
    group_card_for_day,
    group_event_spread_for_day,
    party_prompt_for_day,
    private_deep_link,
)
from app.domain.reading import SymbolOrientation
from app.domain.tarot import RWS_78_V1


def test_group_card_is_stable_for_chat_and_day() -> None:
    day = date(2026, 8, 16)

    first = group_card_for_day(-1001234567890, day)
    second = group_card_for_day(-1001234567890, day)

    assert first == second
    assert first.card in RWS_78_V1.cards
    assert first.orientation in {SymbolOrientation.UPRIGHT, SymbolOrientation.REVERSED}
    assert first.theme.strip()


def test_compatibility_is_symmetric_and_bounded() -> None:
    day = date(2026, 8, 16)

    forward = compatibility_for_day(101, 202, day)
    reverse = compatibility_for_day(202, 101, day)

    assert forward == reverse
    assert forward.card in RWS_78_V1.cards
    assert 45 <= forward.communication <= 95
    assert 45 <= forward.spontaneity <= 95
    assert 45 <= forward.teamwork <= 95


def test_party_prompt_is_stable_and_never_selects_a_member() -> None:
    day = date(2026, 8, 16)

    first = party_prompt_for_day(-1001234567890, day)
    second = party_prompt_for_day(-1001234567890, day)

    assert first == second
    assert first.prompt.strip()
    assert first.archetype in RWS_78_V1.cards
    assert "@" not in first.prompt


def test_group_event_spread_is_fixed_to_safe_kinds_and_unique_cards() -> None:
    day = date(2026, 8, 16)

    for event_kind in GROUP_EVENT_KINDS:
        first = group_event_spread_for_day(-1001234567890, day, event_kind)
        second = group_event_spread_for_day(-1001234567890, day, event_kind)

        assert first == second
        assert first.event_kind == event_kind
        assert len(first.cards) == 3
        assert len({card.code for card in first.cards}) == 3
        assert all(card in RWS_78_V1.cards for card in first.cards)

    with pytest.raises(ValueError):
        group_event_spread_for_day(-1001234567890, day, "отношения")


def test_group_commands_are_explicit_party_actions_only() -> None:
    expected_commands = [
        "card",
        "compatibility",
        "party",
        "event",
        "grouphelp",
    ]
    assert [command.command for command in GROUP_COMMANDS] == expected_commands

    help_command_lines = [
        match.group(1)
        for line in GROUP_HELP.splitlines()
        if (match := re.search(r"/(\w+)\s+—", line)) is not None
    ]
    assert help_command_lines == expected_commands
    assert "/event вечер —" not in GROUP_HELP
    assert "/event поездка —" not in GROUP_HELP
    assert "/event событие —" not in GROUP_HELP
    assert "после команды напишите: вечер, поездка или событие" in GROUP_HELP
    assert "Личные вопросы лучше задавать Numa один на один" in GROUP_HELP


def test_group_deep_links_can_only_enter_existing_personas() -> None:
    assert private_deep_link("@numa_bot", "tarot") == "https://t.me/numa_bot?start=tarot"
    assert private_deep_link("numa_bot", "love") == "https://t.me/numa_bot?start=love"

    with pytest.raises(ValueError):
        private_deep_link("numa_bot", "refund")
    with pytest.raises(ValueError):
        private_deep_link("", "tarot")
