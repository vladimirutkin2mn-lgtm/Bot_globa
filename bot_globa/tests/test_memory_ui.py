"""User-facing oracle-memory provenance and Telegram callback invariants."""

from datetime import UTC, datetime
from uuid import uuid4

from aiogram.types import InlineKeyboardMarkup

from app.bot.keyboards import main_menu_keyboard, more_menu_keyboard
from app.bot.memory_handlers import _parse_item_page, _source_label
from app.bot.memory_keyboards import (
    memory_clear_confirmation_keyboard,
    memory_delete_confirmation_keyboard,
    memory_disabled_keyboard,
    memory_edit_cancel_keyboard,
    memory_enabled_keyboard,
    memory_item_keyboard,
    memory_list_keyboard,
    memory_revoke_confirmation_keyboard,
)
from app.domain.oracle_memory import (
    MemoryClaimBasis,
    MemoryItemView,
    MemoryKind,
    MemorySourceType,
)


def _item(
    *,
    claim_basis: MemoryClaimBasis,
    source_type: MemorySourceType,
    reading_date: datetime | None,
) -> MemoryItemView:
    return MemoryItemView(
        id=uuid4(),
        kind=MemoryKind.USER_STATEMENT,
        value="A durable memory value",
        confidence_milli=800,
        claim_basis=claim_basis,
        source_type=source_type,
        source_reading_id=uuid4() if reading_date is not None else None,
        source_reading_created_at=reading_date,
        source_persona_code="tarot_reader" if reading_date is not None else None,
        extraction_version="test-v1",
        candidate_key="candidate-v1" if reading_date is not None else None,
        created_at=datetime(2026, 8, 7, tzinfo=UTC),
    )


def _callback_values(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def test_memory_provenance_labels_distinguish_epistemic_basis() -> None:
    reading_date = datetime(2026, 8, 6, tzinfo=UTC)
    inferred = _item(
        claim_basis=MemoryClaimBasis.MODEL_INFERRED,
        source_type=MemorySourceType.READING_DERIVED,
        reading_date=reading_date,
    )
    user_stated = _item(
        claim_basis=MemoryClaimBasis.USER_STATED,
        source_type=MemorySourceType.READING_DERIVED,
        reading_date=reading_date,
    )
    correction = _item(
        claim_basis=MemoryClaimBasis.USER_STATED,
        source_type=MemorySourceType.USER_EXPLICIT,
        reading_date=None,
    )

    assert _source_label(inferred) == "бот предположил это на основании расклада от 06.08.2026"
    assert _source_label(user_stated) == "вы сообщили это в раскладе от 06.08.2026"
    assert _source_label(correction) == "вы исправили или добавили это напрямую · 07.08.2026"


def test_memory_controls_are_discoverable_and_fit_telegram_callback_limit() -> None:
    item_id = uuid4()
    keyboards = (
        main_menu_keyboard(),
        more_menu_keyboard(),
        memory_disabled_keyboard(),
        memory_enabled_keyboard(True),
        memory_list_keyboard(
            ((item_id, 1),),
            page=0,
            has_previous=False,
            has_next=True,
        ),
        memory_item_keyboard(item_id, 0),
        memory_edit_cancel_keyboard(0),
        memory_delete_confirmation_keyboard(item_id, 0),
        memory_clear_confirmation_keyboard(),
        memory_revoke_confirmation_keyboard(),
    )
    callbacks = [value for keyboard in keyboards for value in _callback_values(keyboard)]

    assert "menu:memory" in callbacks
    assert callbacks
    assert all(len(value.encode("utf-8")) <= 64 for value in callbacks)


def test_memory_item_callback_parser_rejects_malformed_ids() -> None:
    item_id = uuid4()
    assert _parse_item_page(f"memory:open:{item_id}:3", "memory:open:") == (item_id, 3)
    assert _parse_item_page("memory:open:not-a-uuid:3", "memory:open:") is None
    assert _parse_item_page(f"memory:open:{item_id}:bad", "memory:open:") is None
