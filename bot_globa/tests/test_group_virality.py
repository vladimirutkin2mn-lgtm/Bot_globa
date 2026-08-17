import re
from datetime import date

import pytest
from aiogram.types import InlineKeyboardMarkup

from app.bot.commands import GROUP_COMMANDS
from app.bot.group_handlers import (
    GROUP_EVENT_KINDS,
    GROUP_HELP,
    PARTY_PROMPTS,
    _append_back,
    _party_menu_keyboard,
    _party_result_keyboard,
    chat_archetype_for_day,
    compatibility_for_day,
    duel_for_day,
    group_card_for_day,
    group_event_spread_for_day,
    party_prompt_for_day,
    party_vibe_for_day,
    private_deep_link,
)
from app.domain.reading import SymbolOrientation
from app.domain.tarot import RWS_78_V1


def _callbacks(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def test_group_card_is_stable_for_chat_and_day() -> None:
    day = date(2026, 8, 16)

    first = group_card_for_day(-1001234567890, day)
    second = group_card_for_day(-1001234567890, day)

    assert first == second
    assert first.card in RWS_78_V1.cards
    assert first.orientation in {SymbolOrientation.UPRIGHT, SymbolOrientation.REVERSED}
    assert first.theme.strip()


def test_chat_archetype_is_stable_for_chat_and_day() -> None:
    day = date(2026, 8, 16)

    first = chat_archetype_for_day(-1001234567890, day)
    second = chat_archetype_for_day(-1001234567890, day)

    assert first == second
    assert first in RWS_78_V1.cards


def test_compatibility_is_symmetric_and_bounded() -> None:
    day = date(2026, 8, 16)

    forward = compatibility_for_day(101, 202, day)
    reverse = compatibility_for_day(202, 101, day)

    assert forward == reverse
    assert forward.card in RWS_78_V1.cards
    assert 45 <= forward.communication <= 95
    assert 45 <= forward.spontaneity <= 95
    assert 45 <= forward.teamwork <= 95


def test_duel_is_stable_and_uses_three_distinct_cards() -> None:
    day = date(2026, 8, 16)

    first = duel_for_day(101, 202, day)
    second = duel_for_day(101, 202, day)

    assert first == second
    assert {first.first_card, first.second_card, first.dynamic_card} <= set(RWS_78_V1.cards)
    assert len({first.first_card.code, first.second_card.code, first.dynamic_card.code}) == 3

    with pytest.raises(ValueError):
        duel_for_day(101, 101, day)


def test_party_prompt_is_stable_rotating_and_never_selects_a_member() -> None:
    day = date(2026, 8, 16)

    first = party_prompt_for_day(-1001234567890, day)
    second = party_prompt_for_day(-1001234567890, day)
    next_round = party_prompt_for_day(-1001234567890, day, 1)

    assert first == second
    assert first.prompt.strip()
    assert first.archetype in RWS_78_V1.cards
    assert "@" not in first.prompt
    assert next_round.prompt in PARTY_PROMPTS
    assert next_round.prompt != first.prompt

    with pytest.raises(ValueError):
        party_prompt_for_day(-1001234567890, day, -1)


def test_party_vibe_is_stable_for_chat_and_day() -> None:
    day = date(2026, 8, 16)

    first = party_vibe_for_day(-1001234567890, day)
    second = party_vibe_for_day(-1001234567890, day)

    assert first == second
    assert first.title.strip()
    assert first.text.strip()
    assert first.card in RWS_78_V1.cards


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


def test_party_menu_only_contains_party_games() -> None:
    party = _party_menu_keyboard()

    assert _callbacks(party) == ["group:party:who:0", "group:party:vibe"]
    assert [button.text for row in party.inline_keyboard for button in row] == [
        "🎲 Кто сегодня…",
        "🔥 Тема вечера",
    ]


def test_nested_group_results_can_return_to_their_picker() -> None:
    party = _party_result_keyboard("numa_bot", 1)
    event = _append_back(
        None,
        text="← К выбору события",
        callback_data="group:event:menu",
    )

    assert _callbacks(party)[-1] == "group:party:menu"
    assert party.inline_keyboard[-1][0].text == "← К играм"
    assert _callbacks(event) == ["group:event:menu"]
    assert event.inline_keyboard[-1][0].text == "← К выбору события"


def test_group_commands_match_help_one_to_one() -> None:
    expected_commands = [
        "card",
        "compatibility",
        "party",
        "event",
        "chat",
        "grouphelp",
    ]
    assert [command.command for command in GROUP_COMMANDS] == expected_commands

    compatibility_command = next(
        command for command in GROUP_COMMANDS if command.command == "compatibility"
    )
    assert compatibility_command.is_ephemeral is True
    assert "Ответьте на сообщение" in compatibility_command.description
    assert all(
        command.is_ephemeral is not True
        for command in GROUP_COMMANDS
        if command.command != "compatibility"
    )

    command_block = GROUP_HELP.split("Команды:\n\n", 1)[1].split("\n\nКак использовать:", 1)[0]
    help_command_lines = [
        match.group(1)
        for line in command_block.splitlines()
        if (match := re.search(r"/(\w+)\s+—", line)) is not None
    ]
    assert help_command_lines == expected_commands
    assert "/event вечер —" not in GROUP_HELP
    assert "/event поездка —" not in GROUP_HELP
    assert "/event событие —" not in GROUP_HELP
    assert "• /compatibility — ответьте командой на сообщение человека." in GROUP_HELP
    assert "• /party — выберите игру кнопкой." in GROUP_HELP
    assert "• /event — выберите вечер, поездку или событие кнопкой." in GROUP_HELP
    assert "Личные вопросы лучше задавать Numa один на один" in GROUP_HELP


def test_group_deep_links_can_only_enter_existing_personas() -> None:
    assert private_deep_link("@numa_bot", "tarot") == "https://t.me/numa_bot?start=tarot"
    assert private_deep_link("numa_bot", "love") == "https://t.me/numa_bot?start=love"

    with pytest.raises(ValueError):
        private_deep_link("numa_bot", "refund")
    with pytest.raises(ValueError):
        private_deep_link("", "tarot")
