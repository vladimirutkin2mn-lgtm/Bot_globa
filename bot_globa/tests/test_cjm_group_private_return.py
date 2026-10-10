from aiogram.types import InlineKeyboardMarkup

from app.bot import group_private_cjm
from app.domain.synastry import CompatibilityContext


def test_compatibility_private_astro_cta_says_to_create_map_and_return(monkeypatch) -> None:
    def previous(*args, **kwargs):
        return InlineKeyboardMarkup(inline_keyboard=[])

    monkeypatch.setattr(group_private_cjm, "_PREVIOUS_PRECISION_KEYBOARD", previous)

    keyboard = group_private_cjm._precision_keyboard_with_private(
        "NumaBot",
        context=CompatibilityContext.WORK,
        first_id=1,
        second_id=2,
        first_name="A",
        second_name="B",
    )

    button = keyboard.inline_keyboard[0][0]
    assert button.text == "🪐 Создать карту и вернуться"
    assert button.callback_data == "p108:private:compatibility:astro"
