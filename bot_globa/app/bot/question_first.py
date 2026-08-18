"""Question-first entry layer that reuses existing persona/topic flows."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import texts
from app.bot.keyboards import main_menu_keyboard, oracle_menu_keyboard
from app.bot.scene_media import Scene
from app.bot.screen import show_screen

router = Router(name="question_first")


@router.callback_query(F.data == "menu:oracles")
async def oracle_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Keep personas available as a secondary navigation layer."""

    await callback.answer()
    await state.clear()
    if isinstance(callback.message, Message):
        await show_screen(
            callback.message,
            Scene.MAIN_MENU,
            texts.ORACLE_MENU,
            reply_markup=oracle_menu_keyboard(),
            state=state,
        )


@router.callback_query(F.data == "menu:questions")
async def question_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Return from the persona shelf to the primary question-first entry screen."""

    await callback.answer()
    await state.clear()
    if isinstance(callback.message, Message):
        await show_screen(
            callback.message,
            Scene.MAIN_MENU,
            texts.MAIN_MENU,
            reply_markup=main_menu_keyboard(),
            state=state,
        )
