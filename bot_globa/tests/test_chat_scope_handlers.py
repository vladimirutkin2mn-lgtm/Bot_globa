"""P0 chat-scope guards keep private product flows out of group chats."""

from pathlib import Path

from app.bot.chat_scope_handlers import (
    GROUP_ENTRY_TEXT,
    is_personal_callback_data,
    private_payload_for_callback,
    private_payload_for_command,
)


def test_personal_callbacks_are_guarded_but_group_games_are_not() -> None:
    for data in (
        "menu:astro",
        "oracle:auto",
        "love:topic:boundaries",
        "memory:settings",
        "credits:buy:single",
        "daily:share",
        "story:open:1",
    ):
        assert is_personal_callback_data(data)

    for data in (
        "group:party:who:0",
        "gc:c:l:1:2:3",
        "g2:z:c:pair:xx:0:ari",
        "p108:private:compatibility:love",
        "v:d:1:2",
    ):
        assert not is_personal_callback_data(data)


def test_private_redirect_preserves_only_explicit_practice() -> None:
    assert private_payload_for_command("/love@numa_test_bot") == "love"
    assert private_payload_for_command("/astro") == "astro"
    assert private_payload_for_command("/settings") is None
    assert private_payload_for_callback("menu:tarot") == "tarot"
    assert private_payload_for_callback("psy:topic:reflection") == "psy"
    assert private_payload_for_callback("credits:buy:single") is None


def test_group_entry_points_to_group_mechanics_without_personal_input() -> None:
    assert "/compatibility" in GROUP_ENTRY_TEXT
    assert "/duel" in GROUP_ENTRY_TEXT
    assert "читать обычную переписку" in GROUP_ENTRY_TEXT


def test_chat_scope_router_is_registered_before_personal_routers() -> None:
    source = Path("app/bot/main.py").read_text(encoding="utf-8")
    guard = source.index("dispatcher.include_router(chat_scope_router)")
    assert guard < source.index("dispatcher.include_router(telegram_stars_router)")
    assert guard < source.index("dispatcher.include_router(memory_router)")
    assert guard < source.index("dispatcher.include_router(personal_oracle_router)")
    assert guard < source.index("dispatcher.include_router(create_persona_router(flow))")
