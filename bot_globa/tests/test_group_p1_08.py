from collections.abc import Mapping
from typing import Any, cast

import pytest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, User

from app.bot import group_p1_08 as p1
from app.bot import group_viral_upgrade as viral_upgrade
from app.domain.natal_chart import NatalChartResult, ZodiacSign
from app.domain.synastry import CompatibilityContext
from app.providers.numa_product_analytics import (
    GROUP_FUNNEL_SOURCE,
    GroupFunnelEvent,
    ProductAnalyticsContractError,
    validate_numa_group_event,
)


class RecordingAnalytics:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, str, dict[str, str]]] = []

    async def track(
        self,
        user_id: str | None,
        event: str,
        properties: Mapping[str, str] | None = None,
    ) -> None:
        self.calls.append((user_id, event, dict(properties or {})))


def _callback(user_id: int, data: str) -> CallbackQuery:
    return CallbackQuery(
        id="callback",
        from_user=User(id=user_id, is_bot=False, first_name="Player"),
        chat_instance="chat",
        data=data,
    )


def test_group_funnel_contract_accepts_only_aggregate_source_and_game_codes() -> None:
    safe = validate_numa_group_event(
        GroupFunnelEvent.GAME_STARTED.value,
        {"source": GROUP_FUNNEL_SOURCE, "game": "compatibility"},
    )

    assert safe == {"source": "group_add", "game": "compatibility"}
    for forbidden in ("user_id", "chat_id", "member_id", "text", "question"):
        with pytest.raises(ProductAnalyticsContractError):
            validate_numa_group_event(
                GroupFunnelEvent.GAME_STARTED.value,
                {
                    "source": GROUP_FUNNEL_SOURCE,
                    "game": "compatibility",
                    forbidden: "123",
                },
            )


async def test_group_funnel_tracking_never_sets_a_subject_id() -> None:
    analytics = RecordingAnalytics()

    await p1._track_group(
        analytics,
        GroupFunnelEvent.GAME_COMPLETED,
        game="duel",
    )

    assert analytics.calls == [
        (
            None,
            "group_game_completed",
            {"source": "group_add", "game": "duel"},
        )
    ]


def test_private_friends_link_requests_no_admin_permissions() -> None:
    keyboard = p1._friends_add_keyboard("numa_bot")
    url = keyboard.inline_keyboard[0][0].url

    assert url == "https://t.me/numa_bot?startgroup=party"
    assert "admin=" not in url


def test_group_private_cta_becomes_trackable_without_ids() -> None:
    original = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🪐 Сделать точнее",
                    url="https://t.me/numa_bot?start=astro",
                )
            ]
        ]
    )

    tracked = p1._private_tracking_keyboard(original, game="compatibility")
    button = tracked.inline_keyboard[0][0]

    assert button.url is None
    assert button.callback_data == "p108:private:compatibility:astro"
    assert all(char.isdigit() is False for char in button.callback_data)


def test_each_player_must_choose_their_own_sign_before_quick_result() -> None:
    first_id, second_id = 101, 202
    pair = viral_upgrade._pair_payload(first_id, second_id)
    aries = viral_upgrade._SIGN_CODE[ZodiacSign.ARIES]
    libra = viral_upgrade._SIGN_CODE[ZodiacSign.LIBRA]

    first_choice = _callback(first_id, f"g2:z:c:{pair}:x.x:0:{aries}")
    wrong_second = _callback(first_id, f"g2:z:c:{pair}:{aries}.x:1:{libra}")
    second_choice = _callback(second_id, f"g2:z:c:{pair}:{aries}.x:1:{libra}")

    assert p1._final_sign_game(first_choice) is None
    assert p1._final_sign_game(wrong_second) is None
    assert p1._final_sign_game(second_choice) == "compatibility"


async def test_compatibility_without_natal_profiles_uses_existing_sign_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    async def pair_names(*args: object, **kwargs: object) -> tuple[str, str]:
        return "First", "Second"

    async def chart_for(*args: object, **kwargs: object) -> None:
        return None

    async def missing_screen(*args: object, **kwargs: object) -> None:
        seen.update(kwargs)

    async def should_not_delegate(*args: object, **kwargs: object) -> None:
        raise AssertionError("natal renderer must not run when a profile is missing")

    monkeypatch.setattr(p1.compatibility, "_pair_names", pair_names)
    monkeypatch.setattr(p1.compatibility, "_chart_for", chart_for)
    monkeypatch.setattr(p1.viral_upgrade, "_missing_screen", missing_screen)
    monkeypatch.setattr(p1, "_PREVIOUS_COMPATIBILITY_RENDER", should_not_delegate)

    await p1._render_compatibility_p1_08(
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
        context=CompatibilityContext.LOVE,
        inviter_id=1,
        first_id=101,
        second_id=202,
    )

    assert seen["mode"] == "c"
    assert seen["first_name"] == "First"
    assert seen["second_name"] == "Second"


async def test_compatibility_keeps_full_natal_renderer_when_both_profiles_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delegated = False
    chart = cast(NatalChartResult, object())

    async def pair_names(*args: object, **kwargs: object) -> tuple[str, str]:
        return "First", "Second"

    async def chart_for(*args: object, **kwargs: object) -> NatalChartResult:
        return chart

    async def delegate(*args: object, **kwargs: object) -> None:
        nonlocal delegated
        delegated = True

    monkeypatch.setattr(p1.compatibility, "_pair_names", pair_names)
    monkeypatch.setattr(p1.compatibility, "_chart_for", chart_for)
    monkeypatch.setattr(p1, "_PREVIOUS_COMPATIBILITY_RENDER", delegate)

    await p1._render_compatibility_p1_08(
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
        context=CompatibilityContext.LOVE,
        inviter_id=1,
        first_id=101,
        second_id=202,
    )

    assert delegated is True
