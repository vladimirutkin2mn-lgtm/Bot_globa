"""One callback must reach exactly one persona.

`create_persona_router` builds three structurally identical routers that differ only by
namespace, so the failure this file guards against is a callback or an FSM state leaking
from one persona into another.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from aiogram import Router
from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.persona_flow import PersonaFlow
from app.bot.persona_flows import MVP_READING_FLOWS
from app.bot.persona_handlers import create_persona_router

ROUTERS: dict[str, Router] = {
    flow.namespace: create_persona_router(flow) for flow in MVP_READING_FLOWS
}


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
    """Yield (namespace, handler name) for every router that accepts this callback."""
    event = _callback(data)
    for namespace, router in ROUTERS.items():
        for handler in router.callback_query.handlers:
            magics = [item.magic for item in handler.filters or () if item.magic is not None]
            if magics and all(magic.resolve(event) for magic in magics):
                yield namespace, handler.callback.__name__


def _payloads(flow: PersonaFlow) -> list[str]:
    reading_id = str(uuid4())
    topic = next(iter(flow.topic_labels))
    return [
        f"menu:{flow.namespace}",
        f"onboarding:consent:{flow.namespace}",
        flow.callback("new"),
        flow.callback("cancel"),
        flow.callback("menu"),
        flow.callback("history"),
        flow.callback("history", "page", "1"),
        flow.callback("history", "open", reading_id),
        flow.callback("topic", topic),
        flow.callback("example"),
        flow.callback("context", "skip"),
        flow.callback("retry", reading_id),
        flow.callback("unlock", reading_id),
    ]


@pytest.mark.parametrize("flow", MVP_READING_FLOWS, ids=lambda flow: flow.persona_code)
def test_every_callback_reaches_exactly_one_handler_of_its_own_persona(
    flow: PersonaFlow,
) -> None:
    for payload in _payloads(flow):
        matches = list(_matches(payload))
        assert len(matches) == 1, f"{payload} matched {matches}"
        namespace, _ = matches[0]
        assert namespace == flow.namespace, f"{payload} was routed to {namespace}"


def test_no_two_personas_answer_the_same_callback() -> None:
    seen: dict[str, str] = {}
    for flow in MVP_READING_FLOWS:
        for payload in _payloads(flow):
            owner = seen.setdefault(payload, flow.namespace)
            assert owner == flow.namespace, f"{payload} is claimed by {owner} too"


def test_history_pagination_does_not_swallow_the_history_root() -> None:
    """`history:page:N` and `history:open:ID` must not shadow plain `history`."""
    for flow in MVP_READING_FLOWS:
        root = {handler for _, handler in _matches(flow.callback("history"))}
        page = {handler for _, handler in _matches(flow.callback("history", "page", "2"))}

        assert root == {"show_history"}
        assert page == {"show_history_page"}


def test_each_router_is_named_after_its_persona_namespace() -> None:
    assert {name: router.name for name, router in ROUTERS.items()} == {
        flow.namespace: flow.namespace for flow in MVP_READING_FLOWS
    }


def test_message_handlers_are_bound_to_the_personas_own_states() -> None:
    for flow in MVP_READING_FLOWS:
        router = ROUTERS[flow.namespace]
        registered = {handler.callback.__name__ for handler in router.message.handlers}

        assert registered == {
            "start_from_command",
            "receive_question",
            "receive_context",
            "already_generating",
        }
        other_states = {
            state.state
            for other in MVP_READING_FLOWS
            if other is not flow
            for state in (
                other.states.waiting_for_question,
                other.states.waiting_for_context,
                other.states.generating,
            )
        }
        own_states = {
            flow.states.waiting_for_question.state,
            flow.states.waiting_for_context.state,
            flow.states.generating.state,
        }
        assert not own_states & other_states
