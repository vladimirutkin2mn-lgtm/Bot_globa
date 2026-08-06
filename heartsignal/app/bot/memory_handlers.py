"""Telegram controls for explicit-consent oracle memory."""

# ruff: noqa: RUF001

from math import ceil
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import main_menu_keyboard
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
from app.bot.states import MemoryStates
from app.domain.oracle_memory import (
    MemoryClaimBasis,
    MemoryItemView,
    MemoryKind,
    MemorySourceType,
)
from app.services.onboarding import OnboardingService
from app.services.oracle_memory import MemoryConsentRequiredError, OracleMemoryService

router = Router(name="oracle-memory")
_PAGE_SIZE = 5
_NOT_ONBOARDED = "Сначала отправьте /start и завершите подтверждение возраста и условий."
_STALE = "Эта запись уже недоступна. Откройте список памяти заново."
_INVALID_CORRECTION = "Отправьте непустой текст длиной до 2000 символов."

_KIND_LABELS = {
    MemoryKind.USER_STATEMENT: "Факт или контекст",
    MemoryKind.USER_PREFERENCE: "Предпочтение",
    MemoryKind.PERSONAL_GOAL: "Цель",
    MemoryKind.RELATIONSHIP_NOTES: "Контекст отношений",
    MemoryKind.RECURRING_THEME: "Повторяющаяся тема",
    MemoryKind.BIRTH_PROFILE: "Данные профиля",
    MemoryKind.ORACLE_PREFERENCE: "Предпочтение раскладов",
}


@router.message(Command("memory"))
async def memory_command(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    oracle_memory: OracleMemoryService,
) -> None:
    if message.from_user is None:
        return
    await _show_home(message, message.from_user.id, state, onboarding, oracle_memory)


@router.callback_query(F.data.in_({"menu:memory", "memory:home"}))
async def memory_home(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    oracle_memory: OracleMemoryService,
) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _show_home(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            oracle_memory,
        )


@router.callback_query(F.data == "memory:menu")
async def memory_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.answer("Главное меню", reply_markup=main_menu_keyboard())


@router.callback_query(F.data == "memory:grant")
async def grant_memory(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    oracle_memory: OracleMemoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await state.clear()
        await callback.message.answer(_NOT_ONBOARDED)
        return
    await oracle_memory.grant_consent(user.id)
    await state.clear()
    await callback.message.answer(
        "Память включена. Бот сможет сохранять полезный контекст из готовых раскладов. "
        "Каждую запись можно посмотреть, исправить или удалить.",
        reply_markup=memory_enabled_keyboard(False),
    )


@router.callback_query(F.data.startswith("memory:list:"))
async def list_memory(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    oracle_memory: OracleMemoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    page = _parse_page(callback.data, "memory:list:")
    await _show_list(
        callback.message,
        callback.from_user.id,
        state,
        onboarding,
        oracle_memory,
        page,
    )


@router.callback_query(F.data.startswith("memory:open:"))
async def open_memory_item(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    oracle_memory: OracleMemoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    parsed = _parse_item_page(callback.data, "memory:open:")
    user = await onboarding.current_user(callback.from_user.id)
    if parsed is None or user is None:
        await callback.message.answer(_STALE)
        return
    item_id, page = parsed
    item = await _find_item(oracle_memory, user.id, item_id)
    if item is None:
        await callback.message.answer(_STALE)
        return
    await callback.message.answer(
        _render_detail(item),
        reply_markup=memory_item_keyboard(item.id, page),
    )


@router.callback_query(F.data.startswith("memory:edit_item:"))
async def begin_memory_correction(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    oracle_memory: OracleMemoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    parsed = _parse_item_page(callback.data, "memory:edit_item:")
    user = await onboarding.current_user(callback.from_user.id)
    if parsed is None or user is None:
        await callback.message.answer(_STALE)
        return
    item_id, page = parsed
    if await _find_item(oracle_memory, user.id, item_id) is None:
        await callback.message.answer(_STALE)
        return
    await state.update_data(memory_item_id=str(item_id), memory_page=page)
    await state.set_state(MemoryStates.waiting_for_correction)
    await callback.message.answer(
        "Напишите корректную формулировку одним сообщением. Она будет сохранена как то, "
        "что вы сообщили напрямую, а прежнее зашифрованное значение будет удалено.",
        reply_markup=memory_edit_cancel_keyboard(page),
    )


@router.callback_query(F.data.startswith("memory:edit_cancel:"))
async def cancel_memory_correction(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    page = _parse_page(callback.data, "memory:edit_cancel:")
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Исправление отменено.",
            reply_markup=memory_enabled_keyboard(True),
        )
        await callback.message.answer(
            "Откройте список памяти, чтобы продолжить.",
            reply_markup=memory_list_keyboard(
                (),
                page=page,
                has_previous=False,
                has_next=False,
            ),
        )


@router.message(MemoryStates.waiting_for_correction)
async def save_memory_correction(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    oracle_memory: OracleMemoryService,
) -> None:
    if message.from_user is None:
        return
    value = (message.text or "").strip()
    if not value or len(value) > 2000:
        await message.answer(_INVALID_CORRECTION)
        return
    data = await state.get_data()
    try:
        item_id = UUID(str(data.get("memory_item_id", "")))
    except ValueError:
        await state.clear()
        await message.answer(_STALE)
        return
    user = await onboarding.current_user(message.from_user.id)
    if user is None:
        await state.clear()
        await message.answer(_NOT_ONBOARDED)
        return
    try:
        replacement_id = await oracle_memory.correct_item(user.id, item_id, value)
    except MemoryConsentRequiredError:
        replacement_id = None
    await state.clear()
    if replacement_id is None:
        await message.answer(_STALE, reply_markup=memory_disabled_keyboard())
        return
    await message.answer(
        "Запись исправлена. Новая версия отмечена как сообщённая вами напрямую.",
        reply_markup=memory_enabled_keyboard(True),
    )


@router.callback_query(F.data.startswith("memory:delete:prompt:"))
async def prompt_memory_delete(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    oracle_memory: OracleMemoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    parsed = _parse_item_page(callback.data, "memory:delete:prompt:")
    user = await onboarding.current_user(callback.from_user.id)
    if parsed is None or user is None:
        await callback.message.answer(_STALE)
        return
    item_id, page = parsed
    if await _find_item(oracle_memory, user.id, item_id) is None:
        await callback.message.answer(_STALE)
        return
    await callback.message.answer(
        "Удалить эту запись безвозвратно? Зашифрованное значение будет очищено.",
        reply_markup=memory_delete_confirmation_keyboard(item_id, page),
    )


@router.callback_query(F.data.startswith("memory:delete:confirm:"))
async def confirm_memory_delete(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    oracle_memory: OracleMemoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    parsed = _parse_item_page(callback.data, "memory:delete:confirm:")
    user = await onboarding.current_user(callback.from_user.id)
    if parsed is None or user is None:
        await callback.message.answer(_STALE)
        return
    item_id, page = parsed
    deleted = await oracle_memory.delete_item(user.id, item_id)
    await state.clear()
    await callback.message.answer("Запись удалена." if deleted else _STALE)
    await _show_list(
        callback.message,
        callback.from_user.id,
        state,
        onboarding,
        oracle_memory,
        page,
    )


@router.callback_query(F.data == "memory:clear:prompt")
async def prompt_clear_memory(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Удалить все записи памяти? Память останется включённой для будущих раскладов.",
            reply_markup=memory_clear_confirmation_keyboard(),
        )


@router.callback_query(F.data == "memory:clear:confirm")
async def confirm_clear_memory(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    oracle_memory: OracleMemoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await callback.message.answer(_NOT_ONBOARDED)
        return
    try:
        deleted = await oracle_memory.clear_all(user.id)
    except MemoryConsentRequiredError:
        await callback.message.answer(
            "Память уже отключена.",
            reply_markup=memory_disabled_keyboard(),
        )
        return
    await state.clear()
    await callback.message.answer(
        f"Удалено записей: {deleted}. Память остаётся включённой.",
        reply_markup=memory_enabled_keyboard(False),
    )


@router.callback_query(F.data == "memory:revoke:prompt")
async def prompt_revoke_memory(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Отключить память и удалить все сохранённые значения безвозвратно?",
            reply_markup=memory_revoke_confirmation_keyboard(),
        )


@router.callback_query(F.data == "memory:revoke:confirm")
async def confirm_revoke_memory(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    oracle_memory: OracleMemoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await callback.message.answer(_NOT_ONBOARDED)
        return
    await oracle_memory.revoke_consent(user.id)
    await state.clear()
    await callback.message.answer(
        "Память отключена, все сохранённые значения удалены.",
        reply_markup=memory_disabled_keyboard(),
    )


async def _show_home(
    message: Message,
    telegram_user_id: int,
    state: FSMContext,
    onboarding: OnboardingService,
    oracle_memory: OracleMemoryService,
) -> None:
    await state.clear()
    user = await onboarding.current_user(telegram_user_id)
    if user is None:
        await message.answer(_NOT_ONBOARDED)
        return
    consent = await oracle_memory.consent_state(user.id)
    enabled = bool(consent and consent.permits_memory)
    if not enabled:
        await message.answer(
            "🧠 Память выключена.\n\nЕсли включить её, бот сможет сохранять полезный контекст "
            "из готовых раскладов. Вы сможете увидеть источник каждой записи, исправить её, "
            "удалить отдельно или отключить память с полной очисткой.",
            reply_markup=memory_disabled_keyboard(),
        )
        return
    items = await oracle_memory.list_active(user.id)
    await message.answer(
        f"🧠 Память включена. Сохранено записей: {len(items)}.\n\n"
        "То, что вы сообщили напрямую, и предположения бота помечаются по-разному.",
        reply_markup=memory_enabled_keyboard(bool(items)),
    )


async def _show_list(
    message: Message,
    telegram_user_id: int,
    state: FSMContext,
    onboarding: OnboardingService,
    oracle_memory: OracleMemoryService,
    page: int,
) -> None:
    await state.clear()
    user = await onboarding.current_user(telegram_user_id)
    if user is None:
        await message.answer(_NOT_ONBOARDED)
        return
    items = list(reversed(await oracle_memory.list_active(user.id)))
    if not items:
        await message.answer(
            "Сохранённых записей пока нет.",
            reply_markup=memory_enabled_keyboard(False),
        )
        return
    page_count = ceil(len(items) / _PAGE_SIZE)
    page = min(max(page, 0), page_count - 1)
    start = page * _PAGE_SIZE
    visible = items[start : start + _PAGE_SIZE]
    blocks = [
        f"{start + index + 1}. {_KIND_LABELS[item.kind]}\n"
        f"{_shorten(item.value, 220)}\n"
        f"Источник: {_source_label(item)}"
        for index, item in enumerate(visible)
    ]
    await message.answer(
        "🧠 Что бот помнит\n\n" + "\n\n".join(blocks),
        reply_markup=memory_list_keyboard(
            [(item.id, start + index + 1) for index, item in enumerate(visible)],
            page=page,
            has_previous=page > 0,
            has_next=page + 1 < page_count,
        ),
    )


async def _find_item(
    oracle_memory: OracleMemoryService,
    user_id: UUID,
    item_id: UUID,
) -> MemoryItemView | None:
    return next(
        (item for item in await oracle_memory.list_active(user_id) if item.id == item_id),
        None,
    )


def _render_detail(item: MemoryItemView) -> str:
    return (
        f"🧠 {_KIND_LABELS[item.kind]}\n\n"
        f"{item.value}\n\n"
        f"Источник: {_source_label(item)}\n"
        f"Уверенность извлечения: {item.confidence_milli / 10:.0f}%"
    )


def _source_label(item: MemoryItemView) -> str:
    occurred_at = item.source_reading_created_at or item.created_at
    date = occurred_at.strftime("%d.%m.%Y")
    if item.source_type is MemorySourceType.USER_EXPLICIT:
        return f"вы исправили или добавили это напрямую · {date}"
    if item.claim_basis is MemoryClaimBasis.MODEL_INFERRED:
        return f"бот предположил это на основании расклада от {date}"
    if item.source_type is MemorySourceType.READING_DERIVED:
        return f"вы сообщили это в раскладе от {date}"
    return f"импортировано из профиля · {date}"


def _shorten(value: str, maximum: int) -> str:
    return value if len(value) <= maximum else value[: maximum - 1].rstrip() + "…"


def _parse_page(data: str | None, prefix: str) -> int:
    try:
        return max(int((data or "").removeprefix(prefix)), 0)
    except ValueError:
        return 0


def _parse_item_page(data: str | None, prefix: str) -> tuple[UUID, int] | None:
    tail = (data or "").removeprefix(prefix)
    item_value, separator, page_value = tail.rpartition(":")
    if not separator:
        return None
    try:
        return UUID(item_value), max(int(page_value), 0)
    except ValueError:
        return None
