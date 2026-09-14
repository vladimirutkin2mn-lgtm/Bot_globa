from aiogram.types import InlineKeyboardMarkup

from app.bot import group_compatibility_handlers as compatibility
from app.bot.group_cjm_v3 import (
    _context_sign_keyboard,
    _precision_keyboard,
    compact_group_menu,
    quick_context_text,
)
from app.bot.group_duel_cjm import _party_back_cjm, duel_sign_state
from app.bot.group_viral_upgrade import QuickCompatibility
from app.domain.natal_chart import ZodiacSign
from app.domain.synastry import CompatibilityContext


def _callbacks(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def test_primary_group_menu_contains_only_two_core_games() -> None:
    keyboard = compact_group_menu()
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert [(button.text, button.callback_data) for button in buttons] == [
        ("💞 Совместимость", "gcu:open"),
        ("⚔️ Астро-дуэль", "v:o:d"),
    ]


def test_context_survives_sign_callbacks_within_telegram_limit() -> None:
    pair = (2**52 - 1, 2**52 - 2)

    for context in CompatibilityContext:
        keyboard = _context_sign_keyboard(context, *pair, ("x", "x"), 0)
        callbacks = _callbacks(keyboard)
        assert callbacks
        prefix = f"g3:z:{compatibility._CONTEXT_CODES[context]}:"
        assert all(value.startswith(prefix) for value in callbacks)
        assert all(len(value.encode("utf-8")) <= 64 for value in callbacks)


def test_precision_retry_keeps_selected_context() -> None:
    keyboard = _precision_keyboard(
        "numa_bot",
        context=CompatibilityContext.TRAVEL,
        first_id=101,
        second_id=202,
        first_name="Аня",
        second_name="Миша",
    )

    callbacks = _callbacks(keyboard)
    assert "g3:r:t:2t.5m" in callbacks
    assert all(len(value.encode("utf-8")) <= 64 for value in callbacks)


def test_duel_without_profiles_starts_with_first_missing_sign() -> None:
    signs, slot = duel_sign_state(None, None)

    assert signs == ("x", "x")
    assert slot == 0


def test_duel_result_private_cta_opens_astro_not_tarot() -> None:
    keyboard = _party_back_cjm("numa_bot", "💞 Проверить совместимость")
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert [(button.text, button.callback_data, button.url) for button in buttons] == [
        ("🪐 Разобрать дуэль лично", "p108:private:duel:astro", None),
        ("← К играм", "group:party:menu", None),
    ]


def test_quick_result_uses_selected_context_instead_of_romantic_shipping_copy() -> None:
    result = QuickCompatibility(overall=78, attraction=81, communication=76, long_term=77)

    work = quick_context_text(
        context=CompatibilityContext.WORK,
        first_name="Аня",
        second_name="Миша",
        first_sign=ZodiacSign.ARIES,
        second_sign=ZodiacSign.LIBRA,
        result=result,
        card_name="Мир",
        card_theme="завершение",
    )
    travel = quick_context_text(
        context=CompatibilityContext.TRAVEL,
        first_name="Аня",
        second_name="Миша",
        first_sign=ZodiacSign.ARIES,
        second_sign=ZodiacSign.LIBRA,
        result=result,
        card_name="Мир",
        card_theme="завершение",
    )

    assert "💼 Работа" in work
    assert "Рабочая совместимость" in work
    assert "⚙️ Рабочий ритм" in work
    assert "✈️ Поездка" in travel
    assert "Совместимость в поездке" in travel
    assert "🧭 Совпадение ритма" in travel
    assert "шиппинг" not in work.casefold()
    assert "шиппинг" not in travel.casefold()
