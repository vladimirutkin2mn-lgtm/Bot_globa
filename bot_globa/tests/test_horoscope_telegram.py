"""Transport coverage for the astrologer: routing isolation, keyboards and privacy."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

import pytest
from aiogram import Router
from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot import horoscope_flow as flow
from app.bot.horoscope_flow import HOROSCOPE_FLOW
from app.bot.horoscope_handlers import (
    _parse_date,
    _profile_summary,
    create_horoscope_router,
)
from app.bot.keyboards import main_menu_keyboard
from app.bot.persona_flows import MVP_READING_FLOWS
from app.bot.persona_handlers import create_persona_router
from app.bot.reading_safety_middleware import mvp_safety_intakes
from app.bot.states import HoroscopeStates

ROUTERS: dict[str, Router] = {
    HOROSCOPE_FLOW.namespace: create_horoscope_router(),
    **{persona.namespace: create_persona_router(persona) for persona in MVP_READING_FLOWS},
}
READING_ID = uuid4()


def _callback(data: str) -> CallbackQuery:
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
        from_user=User(id=1, is_bot=False, first_name="Test"),
        text="prompt",
    )
    return CallbackQuery(
        id="callback-1",
        from_user=User(id=1, is_bot=False, first_name="Test"),
        chat_instance="chat-instance",
        data=data,
        message=message,
    )


def _matches(data: str) -> Iterator[tuple[str, str]]:
    event = _callback(data)
    for namespace, router in ROUTERS.items():
        for handler in router.callback_query.handlers:
            magics = [item.magic for item in handler.filters or () if item.magic is not None]
            if magics and all(magic.resolve(event) for magic in magics):
                yield namespace, handler.callback.__name__


ASTRO_PAYLOADS = (
    f"menu:{HOROSCOPE_FLOW.namespace}",
    f"onboarding:consent:{HOROSCOPE_FLOW.namespace}",
    flow.callback("new"),
    flow.callback("cancel"),
    flow.callback("menu"),
    flow.callback("consent", "grant"),
    flow.callback("consent", "decline"),
    flow.callback("place", "pick", "0"),
    flow.callback("place", "retry"),
    flow.callback("time", "unknown"),
    flow.callback("offset", "pick", "120"),
    flow.callback("profile"),
    flow.callback("profile", "edit"),
    flow.callback("profile", "delete"),
    flow.callback("history"),
    flow.callback("history", "page", "1"),
    flow.callback("history", "open", str(READING_ID)),
    flow.callback("topic", "natal_profile"),
    flow.callback("example"),
    flow.callback("context", "skip"),
    flow.callback("retry", str(READING_ID)),
    flow.callback("unlock", str(READING_ID)),
)


@pytest.mark.parametrize("payload", ASTRO_PAYLOADS)
def test_every_astrologer_callback_reaches_exactly_one_astrologer_handler(payload: str) -> None:
    matches = list(_matches(payload))

    assert len(matches) == 1, f"{payload} matched {matches}"
    assert matches[0][0] == HOROSCOPE_FLOW.namespace


@pytest.mark.parametrize("payload", ASTRO_PAYLOADS)
def test_astrologer_callbacks_fit_the_telegram_limit(payload: str) -> None:
    assert len(payload.encode()) <= 64


def test_place_retry_is_not_swallowed_by_the_indexed_place_handler() -> None:
    chosen = {handler for _, handler in _matches(flow.callback("place", "pick", "0"))}
    retry = {handler for _, handler in _matches(flow.callback("place", "retry"))}

    assert chosen == {"choose_place"}
    assert retry == {"retry_place"}


def test_profile_callbacks_do_not_shadow_the_profile_root() -> None:
    root = {handler for _, handler in _matches(flow.callback("profile"))}
    edit = {handler for _, handler in _matches(flow.callback("profile", "edit"))}
    delete = {handler for _, handler in _matches(flow.callback("profile", "delete"))}

    assert root == {"show_profile"}
    assert edit == {"edit_profile"}
    assert delete == {"delete_profile"}


def test_the_astrologer_is_reachable_from_the_main_menu() -> None:
    callbacks = {
        button.callback_data for row in main_menu_keyboard().inline_keyboard for button in row
    }

    assert "oracle:astro" in callbacks
    # Old messages are still supported by the dedicated astrologer router.
    assert list(_matches(f"menu:{HOROSCOPE_FLOW.namespace}"))


def test_the_astrologer_keeps_its_own_state_group() -> None:
    persona_states = {
        state.state
        for persona in MVP_READING_FLOWS
        for state in (
            persona.states.waiting_for_question,
            persona.states.waiting_for_context,
            persona.states.generating,
        )
    }
    astro_states = {
        HoroscopeStates.waiting_for_question.state,
        HoroscopeStates.waiting_for_context.state,
        HoroscopeStates.generating.state,
    }

    assert not persona_states & astro_states


def test_the_astrologer_is_registered_with_the_crisis_middleware() -> None:
    codes = {intake.persona_code for intake in mvp_safety_intakes()}

    assert HOROSCOPE_FLOW.persona_code in codes
    assert codes == {
        "tarot_reader",
        "love_oracle",
        "mystical_psychologist",
        "personal_oracle",
        "astrologer",
        "reading_followup",
    }


def test_topics_keyboard_exposes_only_astrology_native_scopes_plus_profile() -> None:
    callbacks = [
        button.callback_data for row in flow.topics_keyboard().inline_keyboard for button in row
    ]

    for scope in ("natal_profile", "day_forecast", "week_forecast", "month_forecast"):
        assert flow.callback("topic", scope) in callbacks
    assert flow.callback("topic", "decision") not in callbacks
    assert flow.callback("topic", "love") not in callbacks
    assert flow.callback("profile") in callbacks
    # Legacy scopes remain in the contract so stale Telegram buttons still validate.
    assert {"decision", "love"} <= set(flow.HOROSCOPE_TOPIC_LABELS)


def test_place_choice_keyboard_references_candidates_by_index_not_by_name() -> None:
    labels = ["Москва, Россия", "Московский, Россия"]

    keyboard = flow.place_choice_keyboard(labels)
    callbacks = [button.callback_data or "" for row in keyboard.inline_keyboard for button in row]

    assert flow.callback("place", "pick", "0") in callbacks
    assert flow.callback("place", "pick", "1") in callbacks
    assert all("Москва" not in callback for callback in callbacks)
    assert all(len(callback.encode()) <= 64 for callback in callbacks)


def test_profile_summary_shows_the_place_and_moment_but_never_coordinates() -> None:
    exact = _profile_summary("Москва, Россия", date(1990, 7, 12), time(14, 30))
    unknown = _profile_summary("Москва, Россия", date(1990, 7, 12), None)

    assert exact == "Москва, Россия\n12.07.1990, 14:30"
    assert unknown.endswith("время неизвестно")
    assert "55.7" not in exact and "37.6" not in exact


def test_consent_screen_states_where_the_place_is_looked_up_before_any_field_is_asked() -> None:
    """The lookup is now a bundled file, so the copy may not claim an outbound transfer."""

    assert "никуда не передаются" in flow.CONSENT
    assert "внешнему геокодеру" not in flow.CONSENT
    assert "зашифрован" in flow.CONSENT
    callbacks = [
        button.callback_data or ""
        for row in flow.consent_keyboard().inline_keyboard
        for button in row
    ]
    assert callbacks == [flow.callback("consent", "grant"), flow.callback("consent", "decline")]


def test_cancel_is_a_separate_handler_from_starting_over() -> None:
    cancelled = {handler for _, handler in _matches(flow.callback("cancel"))}
    restarted = {handler for _, handler in _matches(flow.callback("new"))}

    assert cancelled == {"cancel"}
    assert restarted == {"restart"}


def test_a_future_birth_date_is_rejected_before_the_geocoder_is_called() -> None:
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)

    assert _parse_date(tomorrow.strftime("%d.%m.%Y")) is None
    assert _parse_date("12.07.1990") == date(1990, 7, 12)
    assert _parse_date("не дата") is None


def test_the_repeated_hour_screen_offers_both_offsets_and_an_escape() -> None:
    keyboard = flow.time_choice_keyboard((60, 120), "02:30")
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    callbacks = [button.callback_data or "" for row in keyboard.inline_keyboard for button in row]

    assert labels[0] == "02:30 — летнее время (UTC+2)"
    assert labels[1] == "02:30 — зимнее время (UTC+1)"
    assert flow.TIME_UNKNOWN_BUTTON in labels
    assert callbacks[:2] == [
        flow.callback("offset", "pick", "120"),
        flow.callback("offset", "pick", "60"),
    ]
    assert all(len(callback.encode()) <= 64 for callback in callbacks)


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(0, "UTC+0"), (180, "UTC+3"), (-300, "UTC−5"), (330, "UTC+5:30"), (-210, "UTC−3:30")],
)
def test_offsets_are_rendered_the_way_a_user_reads_them(minutes: int, expected: str) -> None:
    assert flow.format_offset(minutes) == expected
