from datetime import date

import pytest

from app.bot.commands import GROUP_COMMANDS
from app.bot.group_handlers import (
    GROUP_HELP,
    compatibility_for_day,
    group_card_for_day,
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


def test_group_commands_are_explicit_party_actions_only() -> None:
    assert [command.command for command in GROUP_COMMANDS] == [
        "card",
        "compatibility",
        "grouphelp",
    ]
    assert "не читает историю чата" in GROUP_HELP
    assert "чужих мыслях или чувствах" in GROUP_HELP


def test_group_deep_links_can_only_enter_existing_personas() -> None:
    assert private_deep_link("@numa_bot", "tarot") == "https://t.me/numa_bot?start=tarot"
    assert private_deep_link("numa_bot", "love") == "https://t.me/numa_bot?start=love"

    with pytest.raises(ValueError):
        private_deep_link("numa_bot", "refund")
    with pytest.raises(ValueError):
        private_deep_link("", "tarot")
